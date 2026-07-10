# 桥牌牌型转 PBN 工具

`bridge_pdf_to_pbn.py` 用于把桥牌牌型资料转换成 PBN 文件，并生成校验报告。

本文所有命令都假设你已经在项目根目录下运行。项目根目录就是 `bridge-pbn-converter/`，也就是 `bridge_pdf_to_pbn.py` 和 `README.md` 所在目录。

```bash
cd bridge-pbn-converter
```

## 图形界面版（免环境配置）

如果你不想配置 Python 环境，可以直接使用打包好的 `BridgePBNConverter.exe`（位于 `dist/` 目录）：

1. 双击运行 `BridgePBNConverter.exe`。
2. 选择本地 PDF 文件，或在链接框里粘贴网页 URL（程序会自动识别来源类型）。
3. （可选）点击"参考 PBN（可选）"选择用于比对的参考文件。
4. 输出位置默认就是 exe 所在目录，也可以点击"更改…"切换。
5. 点击"开始转换"，运行日志会实时显示进度与校验结果。

转换完成后，PBN 文件和 CSV 校验报告会输出到指定目录（默认 exe 所在目录）。整个程序是一个单文件 exe，拷到任意 Windows 电脑上双击即可使用，无需安装 Python 或任何依赖。

> 如需从源码重新打包 exe，运行：
> ```bash
> python -m PyInstaller --onefile --windowed --noconfirm \
>   --collect-submodules pdfminer --collect-submodules cryptography \
>   --name BridgePBNConverter bridge_pbn_gui.py
> ```

## 项目结构

输入文件和输出文件统一放在项目根目录下的 `bridge_data/` 目录。

```text
.
├── bridge_pdf_to_pbn.py
├── README.md
├── requirements.txt
├── .gitignore
└── bridge_data/
    ├── 比赛606.pdf
    ├── 比赛606.pbn
    ├── 比赛606_validation_report.csv
    ├── 西翼科技杯 6月团体拉力赛4轮5轮_第1轮.pbn
    └── 西翼科技杯 6月团体拉力赛4轮5轮_第1轮_validation_report.csv
```

如果要转换本地 PDF，先把 PDF 放到 `bridge_data/`。网页 URL 没有本地输入文件，脚本默认也会把输出写到 `bridge_data/`。

## Python 环境准备

推荐使用 conda 环境运行这个项目，避免把依赖装到系统 Python 里。

### 1. 安装 Miniconda

如果本机还没有 `conda` 命令，可以先安装 Miniconda。Apple Silicon Mac 使用：

```bash
curl -L -o /tmp/Miniconda3-latest-MacOSX-arm64.sh \
  https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash /tmp/Miniconda3-latest-MacOSX-arm64.sh -b -p "$HOME/miniconda3"
"$HOME/miniconda3/bin/conda" init zsh
```

执行 `conda init zsh` 后，重新打开终端，或重新加载 shell 配置。

### 2. 创建项目 conda 环境

环境名统一使用 `bridge-pbn`。这里显式指定 `conda-forge` 并加 `--override-channels`，避免默认 Anaconda channels 的 ToS 交互提示。

```bash
conda create -y -n bridge-pbn --override-channels -c conda-forge python=3.12 pip
```

如果环境已经存在，可以跳过这一步。

### 3. 激活环境

```bash
conda activate bridge-pbn
```

### 4. 安装项目依赖

项目依赖写在 `requirements.txt`：

```text
pdfplumber>=0.11,<0.12
```

安装依赖：

```bash
python -m pip install -r requirements.txt
```

后续如果 `requirements.txt` 有变化，可以重新执行：

```bash
python -m pip install -U -r requirements.txt
```

### 5. 确认环境

```bash
python -c "import sys, pdfplumber; print(sys.executable); print(pdfplumber.__version__)"
```

当前项目验证过的环境：

```text
Python 3.12.13
pdfplumber 0.11.10
```

说明：网页 URL 输入只依赖 Python 标准库；PDF 输入必须安装 `pdfplumber`，否则会报 `ModuleNotFoundError: No module named 'pdfplumber'`。

### 6. 可选：只用 pip 安装依赖

如果你不用 conda，也可以在其他 Python 虚拟环境里安装：

```bash
python -m pip install -r requirements.txt
```

### 7. 检查脚本参数

```bash
python bridge_pdf_to_pbn.py --help
```

## 支持范围

脚本支持两类输入源：

1. 本地 PDF 文件路径。
2. 可访问的网页 URL。

脚本支持三种牌型格式：

1. 中国桥牌协会通讯赛 PDF 格式，页面上有中文 `局况`、`发牌`、四家牌型和左下角 HCP 点数。
2. `比赛606.pdf` 这类 `Dlr:` / `Vul:` 风格 PDF。
3. BridgeConex 网页格式，例如：
   `http://www.bridgeconex.com/MatchInfo.aspx?type=31&matchid=26841&rsnum=100&num=-1`

图片输入不支持。脚本不会对 JPG/PNG 做 OCR。

## 基本命令

```bash
python bridge_pdf_to_pbn.py <source> [-o bridge_data/output.pbn] [-r bridge_data/report.csv] [--reference-pbn bridge_data/reference.pbn]
```

参数说明：

| 参数 | 是否必填 | 含义 |
| --- | --- | --- |
| `source` | 是 | 输入源，可以是 `bridge_data/xxx.pdf`，也可以是 `http/https` 网页 URL。 |
| `-o, --output` | 否 | 输出 PBN 文件路径。不传时自动生成文件名。 |
| `-r, --report` | 否 | 输出校验 CSV 路径。不传时默认与 PBN 同目录，文件名为 `<PBN文件名去掉扩展名>_validation_report.csv`。 |
| `--reference-pbn` | 否 | 可选参考 PBN，只用于报告中对比 `Deal` 是否一致，不影响转换。 |

默认输出规则：

1. 输入是 `bridge_data/xxx.pdf` 时，默认输出到同一目录：`bridge_data/xxx.pbn` 和 `bridge_data/xxx_validation_report.csv`。
2. 输入是网页 URL 时，默认输出到 `bridge_data/`，文件名从网页比赛名和轮次提取。
3. 如果手动传了 `-o/-r`，脚本会使用你指定的路径。

## 示例

### 1. 转换 BridgeConex 网页，自动生成文件名

```bash
python bridge_pdf_to_pbn.py 'http://www.bridgeconex.com/MatchInfo.aspx?type=31&matchid=26841&rsnum=100&num=-1'
```

URL 已经放在单引号里时，不需要再写成 `\?`、`\&`、`\=`；脚本会兼容这种复制格式，但推荐直接使用原始 URL。

脚本会从网页中提取比赛名和轮次，例如：

- 比赛名：`西翼科技杯 6月团体拉力赛4轮5轮`
- 轮次：`第1轮`

默认生成：

```text
bridge_data/西翼科技杯 6月团体拉力赛4轮5轮_第1轮.pbn
bridge_data/西翼科技杯 6月团体拉力赛4轮5轮_第1轮_validation_report.csv
```

PBN 头部会写入：

```pbn
%Source: 西翼科技杯 6月团体拉力赛4轮5轮 第1轮
%SourceURL: http://www.bridgeconex.com/MatchInfo.aspx?type=31&matchid=26841&rsnum=100&num=-1
```

### 2. 转换 BridgeConex 网页，手动指定输出文件

```bash
python bridge_pdf_to_pbn.py \
  'http://www.bridgeconex.com/MatchInfo.aspx?type=31&matchid=26841&rsnum=100&num=-1' \
  -o bridge_data/bridgeconex_26841_rs100.pbn \
  -r bridge_data/bridgeconex_26841_rs100_validation_report.csv
```

手动传 `-o/-r` 时，脚本会使用你指定的路径，但 PBN 内的 `%Source` 仍然会从网页提取比赛名和轮次。

### 3. 转换 PDF，自动生成文件名

先把 PDF 放到 `bridge_data/`，然后运行：

```bash
python bridge_pdf_to_pbn.py bridge_data/比赛606.pdf
```

默认生成：

```text
bridge_data/比赛606.pbn
bridge_data/比赛606_validation_report.csv
```

PBN 头部会写入：

```pbn
%Source: 比赛606.pdf
```

### 4. 转换 PDF，手动指定输出文件

```bash
python bridge_pdf_to_pbn.py \
  bridge_data/比赛606.pdf \
  -o bridge_data/比赛606_from_pdf.pbn \
  -r bridge_data/比赛606_validation_report.csv
```

### 5. 带参考 PBN 对比

```bash
python bridge_pdf_to_pbn.py \
  bridge_data/比赛606.pdf \
  --reference-pbn bridge_data/比赛606_reference.pbn
```

`--reference-pbn` 只做差异报告，不会改转换结果。报告中的 `reference_pbn_match` 会显示当前生成的 `Deal` 是否与参考 PBN 一致。

## 输出内容

PBN 文件包含：

```pbn
% PBN 2.1
% EXPORT
%Content-type: text/x-pbn; charset=UTF-8
%Created: ...
%Source: ...

[Board "1"]
[Dealer "N"]
[Vulnerable "None"]
[Deal "N:..."]
```

网页 URL 输入会额外写入 `%SourceURL`。

CSV 校验报告包含：

- `board`：牌号。
- `ok`：该副牌是否通过校验。
- `dealer` / `dealer_expected`：识别到的发牌人和按牌号推导的发牌人。
- `vulnerable` / `vulnerable_expected`：识别到的局况和按牌号推导的局况。
- `deal`：生成的 PBN Deal 字段。
- `calculated_hcp_N/E/S/W`：脚本计算的四家 HCP。
- `printed_hcp_N/E/S/W`：PDF 中印刷的四家 HCP；网页没有这个字段，所以为空。
- `errors`：校验失败原因。
- `reference_pbn_match` / `reference_deal`：传了 `--reference-pbn` 时用于对比。

## 校验规则

每副牌都会做以下校验：

1. 总牌数必须是 52 张。
2. 每种花色必须各 13 张。
3. 不能有重复牌。
4. 不能缺牌。
5. 每张牌必须是合法花色和合法点数。
6. 发牌人必须符合桥牌牌号周期。
7. 局况必须符合桥牌牌号周期。
8. HCP 按 `A=4, K=3, Q=2, J=1, T=0` 计算。
9. PDF 输入会校验印刷 HCP 是否等于计算 HCP。
10. 网页输入没有印刷 HCP，因此只输出计算 HCP，不把印刷 HCP 缺失作为错误。

其中 `10` 会统一转换为 PBN 中的 `T`。

## 退出码

- `0`：所有牌通过校验。
- `1`：至少有一副牌校验失败。

如果输入格式不支持、网页无法访问、PDF 依赖缺失，脚本会抛出错误并停止。

## 常见问题

### `ModuleNotFoundError: No module named 'pdfplumber'`

说明当前没有激活 `bridge-pbn` 环境，或者依赖没有安装完整。先运行：

```bash
conda activate bridge-pbn
python -m pip install -r requirements.txt
python bridge_pdf_to_pbn.py bridge_data/比赛606.pdf
```

### URL 里有 `&` 导致命令异常

URL 必须用引号包起来：

```bash
python bridge_pdf_to_pbn.py 'http://www.bridgeconex.com/MatchInfo.aspx?type=31&matchid=26841&rsnum=100&num=-1'
```

### 路径里有中文或空格

路径建议用引号包起来：

```bash
python bridge_pdf_to_pbn.py 'bridge_data/比赛606.pdf'
```

### 网页提示 `unsupported webpage format`

当前网页解析器只支持 BridgeConex 这种源码里直接包含牌型表格的页面。新网站或动态渲染页面需要单独增加解析规则。
