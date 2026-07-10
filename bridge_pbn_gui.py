#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桥牌 PDF / PBN 转换器 —— 图形界面版

把 bridge_pdf_to_pbn 的全部转换能力封装成桌面程序，无需配置 Python 环境，
双击 EXE 即可使用：

  - 选择本地 PDF 文件，或填入网页链接（自动识别来源类型）
  - （可选）指定参考 PBN，用于校验比对
  - 输出 PBN 与校验报告到「程序所在目录」（可自行更改）
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import bridge_pdf_to_pbn as conv


def app_dir() -> str:
    """程序所在目录：打包后为 exe 目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class _QueueWriter:
    """把 print 输出导向队列，供 GUI 主线程安全刷新日志区。"""

    def __init__(self, q: queue.Queue) -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:  # noqa: D401
        pass


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("桥牌 PDF / PBN 转换器  v2")
        self.root.minsize(600, 540)

        self.out_dir = app_dir()
        self.running = False
        self.log_q: queue.Queue = queue.Queue()

        self._build_ui()
        self._poll_log()

        # 无控制台打包时，未捕获异常也要能提示用户
        sys.excepthook = self._excepthook

    # ------------------------------------------------------------------ 异常
    def _excepthook(self, etype, exc, tb) -> None:
        msg = "".join(traceback.format_exception(etype, exc, tb))
        try:
            with open(os.path.join(app_dir(), "error.log"), "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
        messagebox.showerror("程序错误", msg)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        # 网页链接
        frm_url = ttk.LabelFrame(self.root, text="① 网页链接（直接粘贴 URL）", padding=8)
        frm_url.pack(fill="x", **pad)
        self.url_var = tk.StringVar()
        ttk.Entry(frm_url, textvariable=self.url_var).pack(
            fill="x", expand=True
        )
        ttk.Label(frm_url, text="例如：http://www.bridgeconex.com/MatchInfo.aspx?...",
                  foreground="#999").pack(anchor="w", pady=(4, 0))

        # PDF 文件
        frm_pdf = ttk.LabelFrame(self.root, text="② 本地 PDF 文件", padding=8)
        frm_pdf.pack(fill="x", **pad)
        ttk.Button(frm_pdf, text="选择 PDF 文件…", command=self._pick_pdf).pack(side="left")
        self.pdf_var = tk.StringVar()
        ttk.Entry(frm_pdf, textvariable=self.pdf_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6
        )

        # 参考 PBN（可选）
        frm_ref = ttk.LabelFrame(self.root, text="③ 参考 PBN（可选，用于比对）", padding=8)
        frm_ref.pack(fill="x", **pad)
        ttk.Button(frm_ref, text="选择参考 PBN…", command=self._pick_ref).pack(side="left")
        self.ref_var = tk.StringVar()
        ttk.Entry(frm_ref, textvariable=self.ref_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6
        )

        # 输出位置
        frm_out = ttk.LabelFrame(self.root, text="输出位置（PBN 与校验报告）", padding=8)
        frm_out.pack(fill="x", **pad)
        ttk.Button(frm_out, text="更改…", width=10, command=self._pick_out).pack(side="left")
        self.out_var = tk.StringVar(value=self.out_dir)
        ttk.Entry(frm_out, textvariable=self.out_var, state="readonly").pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Label(frm_out, text="（默认即本程序所在目录）", foreground="#666").pack(side="left")

        # 操作按钮 + 状态
        frm_btn = ttk.Frame(self.root)
        frm_btn.pack(fill="x", **pad)
        self.btn_run = ttk.Button(frm_btn, text="开始转换", command=self._on_run)
        self.btn_run.pack(side="left")
        self.btn_open = ttk.Button(frm_btn, text="打开输出目录", command=self._open_out, state="disabled")
        self.btn_open.pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(frm_btn, textvariable=self.status_var).pack(side="left", padx=12)

        # 运行日志
        frm_log = ttk.LabelFrame(self.root, text="运行日志", padding=8)
        frm_log.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(frm_log, wrap="word", height=12, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(frm_log, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log["yscrollcommand"] = sb.set

    # ------------------------------------------------------------ 交互回调
    def _pick_pdf(self) -> None:
        p = filedialog.askopenfilename(
            title="选择桥牌牌型 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("全部文件", "*.*")],
        )
        if p:
            self.pdf_var.set(p)

    def _pick_ref(self) -> None:
        p = filedialog.askopenfilename(
            title="选择参考 PBN（可选）",
            filetypes=[("PBN 文件", "*.pbn"), ("全部文件", "*.*")],
        )
        if p:
            self.ref_var.set(p)

    def _pick_out(self) -> None:
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.out_dir)
        if d:
            self.out_dir = d
            self.out_var.set(d)

    def _open_out(self) -> None:
        try:
            os.startfile(self.out_dir)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _append_log(self, text: str) -> None:
        self.log["state"] = "normal"
        self.log.insert("end", text)
        self.log.see("end")
        self.log["state"] = "disabled"

    def _poll_log(self) -> None:
        try:
            while True:
                self._append_log(self.log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._poll_log)

    # ------------------------------------------------------------ 转换流程
    def _on_run(self) -> None:
        if self.running:
            return
        pdf = self.pdf_var.get().strip()
        url = self.url_var.get().strip()

        # 来源由 run_conversion 内部自动识别（URL 还是本地文件）
        if url:
            source = url
        elif pdf and os.path.isfile(pdf):
            source = pdf
        else:
            messagebox.showwarning("提示", "请选择 PDF 文件或填写网页链接。")
            return

        ref = self.ref_var.get().strip() or None
        out_dir = self.out_dir
        if not os.path.isdir(out_dir):
            messagebox.showerror("错误", f"输出目录不存在：{out_dir}")
            return

        self.running = True
        self.btn_run["state"] = "disabled"
        self.btn_open["state"] = "disabled"
        self.status_var.set("转换中…")
        self._append_log(f"\n=== 开始转换：{source} ===\n")

        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _QueueWriter(self.log_q)

        def worker() -> None:
            try:
                res = conv.run_conversion(
                    source,
                    reference_pbn=ref,
                    out_dir=out_dir,
                    log=self._log,
                )
                self.log_q.put(
                    f"\n完成：共 {res['total']} 副，通过 {res['passed']}，"
                    f"失败 {res['failed']}\n输出 PBN：{res['pbn_path']}\n"
                )
                self.root.after(0, lambda: self.status_var.set(
                    f"完成：{res['passed']}/{res['total']} 通过"))
                self.root.after(0, lambda: self.btn_open.config(state="normal"))
            except Exception as e:
                self.log_q.put(f"\n转换失败：{e}\n")
                self.root.after(0, lambda: self.status_var.set("失败"))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                self.running = False
                self.root.after(0, lambda: self.btn_run.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _log(*args, **kwargs) -> None:
        print(*args, **kwargs)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
