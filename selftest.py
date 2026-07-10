#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包后的依赖自检：确认 pdfplumber / tkinter / 转换模块均能正常导入。"""
import sys


def main() -> int:
    try:
        import tkinter  # noqa: F401
        import pdfplumber  # noqa: F401
        import bridge_pdf_to_pbn  # noqa: F401
        import bridge_pbn_gui  # noqa: F401
        # 触发 pdfplumber 真实加载路径，避免懒加载遗漏
        from pdfplumber import open as _open  # noqa: F401
        print("IMPORTS_OK")
        return 0
    except Exception as e:
        print(f"IMPORTS_FAIL: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
