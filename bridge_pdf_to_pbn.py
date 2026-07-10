#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert bridge deal PDFs or supported webpages to PBN.

The PDF parsers use text layer coordinates instead of OCR, and the webpage
parser reads the source HTML tables directly.  Every deal is validated before
writing PBN.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from html.parser import HTMLParser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


RANKS = "AKQJT98765432"
RANK_SET = set(RANKS)
SUITS = "SHDC"
SEATS = "NESW"
HCP = {"A": 4, "K": 3, "Q": 2, "J": 1, "T": 0}

VUL_MAP = {"双无": "None", "南北": "NS", "东西": "EW", "双有": "All"}
EN_VUL_MAP = {"None": "None", "N-S": "NS", "E-W": "EW", "Both": "All"}
DEALER_MAP = {"北": "N", "东": "E", "南": "S", "西": "W"}
DEALER_CN = {"N": "北", "E": "东", "S": "南", "W": "西"}
VUL_CN = {"None": "双无", "NS": "南北", "EW": "东西", "All": "双有"}

# PDF layout constants, in PDF points.
COL_BASES = [0.0, 185.0, 370.0]
TOP0 = 85.1
ROW_STEP = 123.0
X_START = {"N": 93.0, "S": 93.0, "W": 35.0, "E": 152.0}
Y_OFF = {"N": 0.0, "W": 33.0, "E": 33.0, "S": 72.0}
SUIT_Y_OFF = [0.0, 12.0, 24.0, 36.0]


@dataclass
class Board:
    number: int
    dealer: str
    vulnerable: str
    hands: dict[str, list[str]]
    printed_hcp: dict[str, int | None]
    metadata_text: str
    require_printed_hcp: bool = True

    def pbn_deal(self) -> str:
        order = clockwise_from(self.dealer)
        hands = [".".join(self.hands[seat]) for seat in order]
        return f"{self.dealer}:{' '.join(hands)}"


@dataclass
class ParsedSource:
    boards: list[Board]
    source_label: str
    filename_stem: str
    source_url: str | None = None
    source_path: Path | None = None


def clockwise_from(seat: str) -> str:
    idx = SEATS.index(seat)
    return SEATS[idx:] + SEATS[:idx]


def expected_dealer(board_no: int) -> str:
    return SEATS[(board_no - 1) % 4]


def expected_vulnerable(board_no: int) -> str:
    cycle = [
        "None",
        "NS",
        "EW",
        "All",
        "NS",
        "EW",
        "All",
        "None",
        "EW",
        "All",
        "None",
        "NS",
        "All",
        "None",
        "NS",
        "EW",
    ]
    return cycle[(board_no - 1) % 16]


def is_card_char(ch: dict) -> bool:
    return (
        ch.get("text") in RANK_SET
        and str(ch.get("fontname", "")).endswith("ArialMT")
        and abs(float(ch.get("size", 0.0)) - 10.0) < 0.25
    )


def is_hcp_char(ch: dict) -> bool:
    return (
        str(ch.get("text", "")).isdigit()
        and str(ch.get("fontname", "")).endswith("ArialMT")
        and abs(float(ch.get("size", 0.0)) - 12.0) < 0.25
    )


def is_zheda_card_char(ch: dict) -> bool:
    return (
        ch.get("text") in RANK_SET
        and 8.0 <= float(ch.get("size", 0.0)) <= 8.8
    )


def is_zheda_hcp_char(ch: dict) -> bool:
    return (
        str(ch.get("text", "")).isdigit()
        and 7.0 <= float(ch.get("size", 0.0)) <= 8.0
    )


def chars_in_box(chars: list[dict], x0: float, x1: float, y0: float, y1: float) -> list[dict]:
    return [
        ch
        for ch in chars
        if x0 <= float(ch["x0"]) <= x1 and y0 <= float(ch["top"]) <= y1
    ]


def require_pdfplumber():
    try:
        import pdfplumber
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PDF input requires pdfplumber. Use the bundled Codex Python runtime, "
            "or install pdfplumber in the current Python environment."
        ) from exc
    return pdfplumber


def read_rank_line(chars: list[dict], base_x: float, top: float, seat: str, suit_idx: int) -> str:
    x0 = base_x + X_START[seat] - 3.0
    x1 = base_x + X_START[seat] + 62.0
    y = top + Y_OFF[seat] + SUIT_Y_OFF[suit_idx]
    found = [ch for ch in chars_in_box(chars, x0, x1, y - 2.0, y + 2.0) if is_card_char(ch)]
    found.sort(key=lambda ch: float(ch["x0"]))
    return "".join(ch["text"] for ch in found)


def read_metadata(chars: list[dict], base_x: float, top: float) -> tuple[str, str, str]:
    found = chars_in_box(chars, base_x + 150.0, base_x + 205.0, top - 4.0, top + 24.0)
    found = [ch for ch in found if float(ch.get("size", 0.0)) < 12.0]
    found.sort(key=lambda ch: (round(float(ch["top"]) / 3.0) * 3.0, float(ch["x0"])))
    text = "".join(ch["text"] for ch in found)

    vulnerable = ""
    dealer = ""
    for cn, value in VUL_MAP.items():
        if cn in text:
            vulnerable = value
            break
    for cn, value in DEALER_MAP.items():
        if f"发牌：{cn}" in text:
            dealer = value
            break
    return text, dealer, vulnerable


def read_printed_hcp(chars: list[dict], base_x: float, top: float) -> dict[str, int | None]:
    windows = {
        "N": (base_x + 42.0, base_x + 62.0, top + 82.0, top + 94.0),
        "W": (base_x + 22.0, base_x + 46.0, top + 92.0, top + 104.0),
        "E": (base_x + 52.0, base_x + 78.0, top + 92.0, top + 104.0),
        "S": (base_x + 42.0, base_x + 62.0, top + 101.0, top + 113.0),
    }
    result: dict[str, int | None] = {}
    for seat, (x0, x1, y0, y1) in windows.items():
        found = [ch for ch in chars_in_box(chars, x0, x1, y0, y1) if is_hcp_char(ch)]
        found.sort(key=lambda ch: float(ch["x0"]))
        value = "".join(ch["text"] for ch in found)
        result[seat] = int(value) if value else None
    return result


def parse_bridge_friends_pdf(pdf_path: Path) -> list[Board]:
    boards: list[Board] = []
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            chars = page.chars
            for row in range(6):
                top = TOP0 + ROW_STEP * row
                for col, base_x in enumerate(COL_BASES):
                    board_no = page_idx * 18 + row * 3 + col + 1
                    metadata, dealer, vulnerable = read_metadata(chars, base_x, top)
                    hands = {
                        seat: [read_rank_line(chars, base_x, top, seat, suit_idx) for suit_idx in range(4)]
                        for seat in SEATS
                    }
                    printed_hcp = read_printed_hcp(chars, base_x, top)
                    boards.append(
                        Board(
                            number=board_no,
                            dealer=dealer,
                            vulnerable=vulnerable,
                            hands=hands,
                            printed_hcp=printed_hcp,
                            metadata_text=metadata,
                        )
                    )
    return boards


def page_contains(page, needle: str) -> bool:
    text = page.extract_text(layout=True, x_density=7.25, y_density=13) or ""
    return needle in text


def group_board_number_chars(chars: list[dict]) -> list[tuple[int, float, float]]:
    candidates = [
        ch
        for ch in chars
        if str(ch.get("text", "")).isdigit()
        and float(ch.get("size", 0.0)) > 15.0
        and float(ch.get("top", 0.0)) > 75.0
        and float(ch.get("x0", 0.0)) < 430.0
    ]
    rows: dict[float, list[dict]] = {}
    for ch in candidates:
        key = round(float(ch["top"]) / 2.0) * 2.0
        rows.setdefault(key, []).append(ch)

    anchors: list[tuple[int, float, float]] = []
    for _, row_chars in sorted(rows.items()):
        row_chars.sort(key=lambda ch: float(ch["x0"]))
        current: list[dict] = []
        for ch in row_chars:
            if current and float(ch["x0"]) - float(current[-1]["x1"]) > 16.0:
                anchors.append(board_anchor_from_chars(current))
                current = []
            current.append(ch)
        if current:
            anchors.append(board_anchor_from_chars(current))

    seen: set[int] = set()
    result: list[tuple[int, float, float]] = []
    for number, x0, top in sorted(anchors):
        if number not in seen:
            seen.add(number)
            result.append((number, x0, top))
    return result


def board_anchor_from_chars(chars: list[dict]) -> tuple[int, float, float]:
    chars.sort(key=lambda ch: float(ch["x0"]))
    return int("".join(ch["text"] for ch in chars)), float(chars[0]["x0"]), float(chars[0]["top"])


def read_zheda_rank_line(chars: list[dict], anchor_x: float, anchor_top: float, seat: str, suit_idx: int) -> str:
    x_windows = {
        "N": (anchor_x + 65.0, anchor_x + 130.0),
        "S": (anchor_x + 65.0, anchor_x + 130.0),
        "W": (anchor_x + 10.0, anchor_x + 88.0),
        "E": (anchor_x + 88.0, anchor_x + 150.0),
    }
    y_offsets = {
        "N": [-8.15, 0.63, 9.50, 18.27],
        "W": [29.67, 38.43, 47.31, 56.07],
        "E": [29.67, 38.43, 47.31, 56.07],
        "S": [66.63, 75.39, 84.27, 93.03],
    }
    x0, x1 = x_windows[seat]
    y = anchor_top + y_offsets[seat][suit_idx]
    found = [ch for ch in chars_in_box(chars, x0, x1, y - 2.2, y + 2.2) if is_zheda_card_char(ch)]
    found.sort(key=lambda ch: float(ch["x0"]))
    return "".join(ch["text"] for ch in found)


def read_zheda_metadata(chars: list[dict], anchor_x: float, anchor_top: float) -> tuple[str, str, str]:
    found = chars_in_box(chars, anchor_x + 118.0, anchor_x + 182.0, anchor_top - 5.0, anchor_top + 26.0)
    found.sort(key=lambda ch: (round(float(ch["top"]) / 2.0) * 2.0, float(ch["x0"])))
    text = "".join(ch["text"] for ch in found)
    dealer_match = re.search(r"Dlr:([NESW])", text)
    vul_match = re.search(r"Vul:(None|N-S|E-W|Both)", text)
    dealer = dealer_match.group(1) if dealer_match else ""
    vulnerable = EN_VUL_MAP.get(vul_match.group(1), "") if vul_match else ""
    return text, dealer, vulnerable


def read_zheda_printed_hcp(chars: list[dict], anchor_x: float, anchor_top: float) -> dict[str, int | None]:
    windows = {
        "N": (anchor_x + 17.0, anchor_x + 34.0, anchor_top + 72.0, anchor_top + 79.5),
        "W": (anchor_x + 8.0, anchor_x + 19.0, anchor_top + 80.0, anchor_top + 85.5),
        "E": (anchor_x + 27.0, anchor_x + 47.0, anchor_top + 80.0, anchor_top + 85.5),
        "S": (anchor_x + 17.0, anchor_x + 34.0, anchor_top + 86.5, anchor_top + 95.0),
    }
    result: dict[str, int | None] = {}
    for seat, (x0, x1, y0, y1) in windows.items():
        found = [ch for ch in chars_in_box(chars, x0, x1, y0, y1) if is_zheda_hcp_char(ch)]
        found.sort(key=lambda ch: float(ch["x0"]))
        value = "".join(ch["text"] for ch in found)
        result[seat] = int(value) if value else None
    return result


def parse_zheda_pdf(pdf_path: Path) -> list[Board]:
    boards: list[Board] = []
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            chars = page.chars
            for board_no, anchor_x, anchor_top in group_board_number_chars(chars):
                metadata, dealer, vulnerable = read_zheda_metadata(chars, anchor_x, anchor_top)
                hands = {
                    seat: [
                        read_zheda_rank_line(chars, anchor_x, anchor_top, seat, suit_idx)
                        for suit_idx in range(4)
                    ]
                    for seat in SEATS
                }
                printed_hcp = read_zheda_printed_hcp(chars, anchor_x, anchor_top)
                boards.append(
                    Board(
                        number=board_no,
                        dealer=dealer,
                        vulnerable=vulnerable,
                        hands=hands,
                        printed_hcp=printed_hcp,
                        metadata_text=metadata,
                    )
                )
    return sorted(boards, key=lambda board: board.number)


def parse_pdf(pdf_path: Path) -> list[Board]:
    pdfplumber = require_pdfplumber()
    with pdfplumber.open(str(pdf_path)) as pdf:
        first_page = pdf.pages[0]
        if page_contains(first_page, "Dlr:") and page_contains(first_page, "Vul:"):
            return parse_zheda_pdf(pdf_path)
    return parse_bridge_friends_pdf(pdf_path)


class HtmlNode:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "HtmlNode | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.parent = parent
        self.children: list[HtmlNode | str] = []

    def text(self) -> str:
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def direct_children(self, tag: str) -> list["HtmlNode"]:
        return [
            child
            for child in self.children
            if isinstance(child, HtmlNode) and child.tag == tag
        ]


class SimpleHtmlParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "br":
            self.stack[-1].children.append("\n")
            return
        node = HtmlNode(tag, {key.lower(): value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def walk_html(node: HtmlNode) -> list[HtmlNode]:
    result: list[HtmlNode] = []
    for child in node.children:
        if isinstance(child, HtmlNode):
            result.append(child)
            result.extend(walk_html(child))
    return result


def normalize_space(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def node_classes(node: HtmlNode) -> set[str]:
    return set(node.attrs.get("class", "").split())


def first_text_by_class(root: HtmlNode, class_name: str) -> str:
    for node in walk_html(root):
        if class_name in node_classes(node):
            text = normalize_space(node.text())
            if text:
                return text
    return ""


def fetch_url_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 bridge_pdf_to_pbn.py"})
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_url_argument(url: str) -> str:
    return re.sub(r"\\([?&=#])", r"\1", url)


def safe_filename_stem(text: str) -> str:
    stem = normalize_space(text)
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    stem = re.sub(r"_+", "_", stem).strip(" ._")
    return stem or "bridge_deals"


WEB_DEALER_MAP = {
    "N": "N",
    "E": "E",
    "S": "S",
    "W": "W",
    "NORTH": "N",
    "EAST": "E",
    "SOUTH": "S",
    "WEST": "W",
    "北": "N",
    "东": "E",
    "南": "S",
    "西": "W",
}

WEB_VUL_MAP = {
    "NONE": "None",
    "NS": "NS",
    "N-S": "NS",
    "NORTH-SOUTH": "NS",
    "EW": "EW",
    "E-W": "EW",
    "EAST-WEST": "EW",
    "BOTH": "All",
    "ALL": "All",
    "双无": "None",
    "南北": "NS",
    "东西": "EW",
    "双有": "All",
}


def normalize_web_ranks(text: str) -> str:
    ranks: list[str] = []
    for token in re.findall(r"10|[AKQJT2-9]", text.upper()):
        rank = "T" if token == "10" else token
        if rank not in RANK_SET:
            raise ValueError(f"invalid rank token in webpage hand: {token}")
        ranks.append(rank)
    return "".join(ranks)


def parse_web_hand(text: str) -> list[str]:
    hand: list[str] = []
    for suit_symbol in ("♠", "♥", "♦", "♣"):
        match = re.search(re.escape(suit_symbol) + r"([^♠♥♦♣]*)", text)
        hand.append(normalize_web_ranks(match.group(1)) if match else "")
    return hand


def parse_bridgeconex_metadata(text: str) -> tuple[int, str, str]:
    normalized = " ".join(text.replace("\xa0", " ").split())
    board_match = re.search(r"牌号\s*(\d+)", normalized)
    dealer_match = re.search(r"发牌\s*([A-Za-z]+|[北东南西])", normalized)
    vul_match = re.search(r"局况\s*([A-Za-z-]+|双无|南北|东西|双有)", normalized)
    if not board_match or not dealer_match or not vul_match:
        raise ValueError(f"cannot parse BridgeConex board metadata: {normalized}")

    dealer_key = dealer_match.group(1).upper()
    vul_key = vul_match.group(1).upper()
    dealer = WEB_DEALER_MAP.get(dealer_key)
    vulnerable = WEB_VUL_MAP.get(vul_key)
    if not dealer or not vulnerable:
        raise ValueError(f"unsupported BridgeConex metadata: {normalized}")
    return int(board_match.group(1)), dealer, vulnerable


def extract_bridgeconex_round(root: HtmlNode, source_url: str) -> str:
    target_rsnum = parse_qs(urlparse(source_url).query).get("rsnum", [""])[0]
    if target_rsnum:
        for node in walk_html(root):
            if node.tag != "a":
                continue
            href_rsnum = parse_qs(urlparse(node.attrs.get("href", "")).query).get("rsnum", [""])[0]
            text = normalize_space(node.text())
            if href_rsnum == target_rsnum and "轮" in text:
                return text

    for node in walk_html(root):
        if "cssRoundMenu" not in node_classes(node):
            continue
        text = normalize_space(node.text())
        if "轮" in text and any(child.attrs.get("color", "").lower() == "red" for child in walk_html(node)):
            return text
    return ""


def bridgeconex_source_metadata(root: HtmlNode, source_url: str) -> tuple[str, str]:
    match_name = first_text_by_class(root, "cssMatchName")
    round_name = extract_bridgeconex_round(root, source_url)
    parts = [part for part in [match_name, round_name] if part]
    if not parts:
        return source_url, safe_filename_stem(urlparse(source_url).netloc or "bridgeconex")
    label = " ".join(parts)
    filename_stem = safe_filename_stem("_".join(parts))
    return label, filename_stem


def parse_bridgeconex_html(text: str, source_url: str) -> ParsedSource:
    parser = SimpleHtmlParser()
    parser.feed(text)
    source_label, filename_stem = bridgeconex_source_metadata(parser.root, source_url)
    board_tables = [
        node
        for node in walk_html(parser.root)
        if node.tag == "table"
        and {"TableFrame_blank1px", "TF_b1px_NofirstOne"} & set(node.attrs.get("class", "").split())
    ]
    if not board_tables:
        raise ValueError("no BridgeConex board tables found in webpage")

    boards: list[Board] = []
    for table in board_tables:
        rows = table.direct_children("tr")
        if len(rows) < 3:
            continue
        cells = [row.direct_children("td") for row in rows[:3]]
        if any(len(row_cells) < 3 for row_cells in cells):
            continue

        board_no, dealer, vulnerable = parse_bridgeconex_metadata(cells[0][2].text())
        hands = {
            "N": parse_web_hand(cells[0][1].text()),
            "W": parse_web_hand(cells[1][0].text()),
            "E": parse_web_hand(cells[1][2].text()),
            "S": parse_web_hand(cells[2][1].text()),
        }
        boards.append(
            Board(
                number=board_no,
                dealer=dealer,
                vulnerable=vulnerable,
                hands=hands,
                printed_hcp={seat: None for seat in SEATS},
                metadata_text=f"{source_url} {board_no}",
                require_printed_hcp=False,
            )
        )
    return ParsedSource(
        boards=sorted(boards, key=lambda board: board.number),
        source_label=source_label,
        filename_stem=filename_stem,
        source_url=source_url,
    )


def parse_url(url: str) -> ParsedSource:
    url = normalize_url_argument(url)
    text = fetch_url_text(url)
    if "bridgeconex.com" in urlparse(url).netloc.lower() or "牌号" in text:
        return parse_bridgeconex_html(text, url)
    raise ValueError("unsupported webpage format")


def is_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_source(source: str) -> list[Board]:
    return parse_source_with_metadata(source).boards


def parse_source_with_metadata(source: str) -> ParsedSource:
    if is_url(source):
        return parse_url(source)
    path = Path(source)
    return ParsedSource(
        boards=parse_pdf(path),
        source_label=path.name,
        filename_stem=safe_filename_stem(path.stem),
        source_path=path,
    )


def hand_cards(hand: list[str]) -> list[str]:
    cards: list[str] = []
    for suit, ranks in zip(SUITS, hand):
        for rank in ranks:
            cards.append(f"{suit}{rank}")
    return cards


def hand_hcp(hand: list[str]) -> int:
    return sum(HCP.get(rank, 0) for ranks in hand for rank in ranks)


def validate_board(board: Board) -> tuple[bool, list[str], dict[str, int]]:
    errors: list[str] = []
    calculated_hcp = {seat: hand_hcp(board.hands[seat]) for seat in SEATS}

    if board.dealer not in SEATS:
        errors.append(f"missing_or_invalid_dealer:{board.metadata_text}")
    if board.vulnerable not in {"None", "NS", "EW", "All"}:
        errors.append(f"missing_or_invalid_vulnerable:{board.metadata_text}")

    if board.dealer and board.dealer != expected_dealer(board.number):
        errors.append(f"dealer_cycle:{board.dealer}!={expected_dealer(board.number)}")
    if board.vulnerable and board.vulnerable != expected_vulnerable(board.number):
        errors.append(f"vulnerable_cycle:{board.vulnerable}!={expected_vulnerable(board.number)}")

    all_cards: list[str] = []
    suit_counts = {suit: 0 for suit in SUITS}
    for seat in SEATS:
        cards = hand_cards(board.hands[seat])
        all_cards.extend(cards)
        if len(cards) != 13:
            errors.append(f"{seat}_card_count:{len(cards)}")
        for card in cards:
            suit, rank = card[0], card[1]
            if suit not in SUITS or rank not in RANK_SET:
                errors.append(f"invalid_card:{card}")
            suit_counts[suit] += 1
        printed_hcp = board.printed_hcp.get(seat)
        if printed_hcp is None:
            if board.require_printed_hcp:
                errors.append(f"{seat}_hcp_missing")
        elif printed_hcp != calculated_hcp[seat]:
            errors.append(f"{seat}_hcp:{calculated_hcp[seat]}!={printed_hcp}")

    if len(all_cards) != 52:
        errors.append(f"deck_count:{len(all_cards)}")
    for suit in SUITS:
        if suit_counts[suit] != 13:
            errors.append(f"{suit}_suit_count:{suit_counts[suit]}")

    duplicates = sorted({card for card in all_cards if all_cards.count(card) > 1})
    if duplicates:
        errors.append("duplicates:" + ",".join(duplicates))

    missing = [f"{suit}{rank}" for suit in SUITS for rank in RANKS if f"{suit}{rank}" not in all_cards]
    if missing:
        errors.append("missing:" + ",".join(missing))

    return not errors, errors, calculated_hcp


def read_reference_pbn(path: Path) -> dict[int, str]:
    if not path:
        return {}
    text = path.read_text(encoding="utf-8")
    boards: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        board_match = re.match(r'\[Board "(\d+)"\]', line)
        if board_match:
            current = int(board_match.group(1))
            continue
        deal_match = re.match(r'\[Deal "([^"]+)"\]', line)
        if deal_match and current is not None:
            boards[current] = deal_match.group(1)
    return boards


def write_pbn(boards: list[Board], output_path: Path, source_label: str, source_url: str | None = None) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "% PBN 2.1",
        "% EXPORT",
        "%Content-type: text/x-pbn; charset=UTF-8",
        f"%Created: {now} bridge_pdf_to_pbn.py",
        f"%Source: {source_label}",
    ]
    if source_url:
        lines.append(f"%SourceURL: {source_url}")
    lines.append("")
    for board in boards:
        lines.extend(
            [
                f'[Board "{board.number}"]',
                f'[Dealer "{board.dealer}"]',
                f'[Vulnerable "{board.vulnerable}"]',
                f'[Deal "{board.pbn_deal()}"]',
                "",
            ]
        )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_report(
    boards: list[Board],
    report_path: Path,
    validation: dict[int, tuple[bool, list[str], dict[str, int]]],
    reference: dict[int, str],
) -> None:
    with report_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "board",
                "ok",
                "dealer",
                "dealer_expected",
                "vulnerable",
                "vulnerable_expected",
                "deal",
                "calculated_hcp_N",
                "printed_hcp_N",
                "calculated_hcp_E",
                "printed_hcp_E",
                "calculated_hcp_S",
                "printed_hcp_S",
                "calculated_hcp_W",
                "printed_hcp_W",
                "errors",
                "reference_pbn_match",
                "reference_deal",
            ]
        )
        for board in boards:
            ok, errors, calculated_hcp = validation[board.number]
            ref_deal = reference.get(board.number, "")
            writer.writerow(
                [
                    board.number,
                    ok,
                    board.dealer,
                    expected_dealer(board.number),
                    board.vulnerable,
                    expected_vulnerable(board.number),
                    board.pbn_deal(),
                    calculated_hcp["N"],
                    board.printed_hcp.get("N"),
                    calculated_hcp["E"],
                    board.printed_hcp.get("E"),
                    calculated_hcp["S"],
                    board.printed_hcp.get("S"),
                    calculated_hcp["W"],
                    board.printed_hcp.get("W"),
                    ";".join(errors),
                    "" if not reference else ref_deal == board.pbn_deal(),
                    ref_deal,
                ]
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert bridge deal PDF or webpage to validated PBN.")
    parser.add_argument("source", help="Input PDF path or webpage URL")
    parser.add_argument("-o", "--output", type=Path, help="Output PBN path. Defaults to source metadata.")
    parser.add_argument("-r", "--report", type=Path, help="Validation CSV report path. Defaults next to the PBN.")
    parser.add_argument("--reference-pbn", type=Path, help="Optional PBN file used only for diff reporting")
    return parser.parse_args(argv)


def default_output_paths(args: argparse.Namespace, parsed: ParsedSource) -> tuple[Path, Path]:
    if args.output:
        output = args.output
    elif parsed.source_path:
        output = parsed.source_path.parent / f"{parsed.filename_stem}.pbn"
    else:
        output = Path("bridge_data") / f"{parsed.filename_stem}.pbn"
    report = args.report or output.with_name(f"{output.stem}_validation_report.csv")
    return output, report


def run_conversion(
    source: str,
    *,
    output: Path | str | None = None,
    report: Path | str | None = None,
    reference_pbn: Path | str | None = None,
    out_dir: Path | str | None = None,
    log=print,
) -> dict:
    """Core conversion pipeline, reusable by the CLI and a GUI.

    Returns a result dict with total/failed/passed counts and output paths.
    ``out_dir`` overrides the output directory (used by the GUI to write next
    to the running executable).
    """
    parsed = parse_source_with_metadata(source)
    boards = parsed.boards
    validation = {board.number: validate_board(board) for board in boards}
    failed = [board_no for board_no, (ok, _, _) in validation.items() if not ok]
    reference = read_reference_pbn(reference_pbn) if reference_pbn else {}

    if output:
        output_path = Path(output)
    elif out_dir:
        output_path = Path(out_dir) / f"{parsed.filename_stem}.pbn"
    elif parsed.source_path:
        output_path = parsed.source_path.parent / f"{parsed.filename_stem}.pbn"
    else:
        output_path = Path("bridge_data") / f"{parsed.filename_stem}.pbn"
    report_path = (
        Path(report) if report
        else output_path.with_name(f"{output_path.stem}_validation_report.csv")
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_pbn(boards, output_path, parsed.source_label, parsed.source_url)
    write_report(boards, report_path, validation, reference)

    ref_mismatches = [
        board.number
        for board in boards
        if reference and reference.get(board.number) != board.pbn_deal()
    ]
    log(f"Parsed boards: {len(boards)}")
    log(f"Source: {parsed.source_label}")
    log(f"Wrote PBN: {output_path}")
    log(f"Wrote report: {report_path}")
    log(f"Validation failures: {len(failed)}")
    if failed:
        log("Failed boards: " + ", ".join(map(str, failed)))
    if reference:
        log(f"Reference mismatches: {len(ref_mismatches)}")
        if ref_mismatches:
            log("Reference mismatch boards: " + ", ".join(map(str, ref_mismatches)))

    return {
        "total": len(boards),
        "failed": len(failed),
        "passed": len(boards) - len(failed),
        "failed_boards": failed,
        "ref_mismatches": ref_mismatches,
        "pbn_path": str(output_path),
        "report_path": str(report_path),
        "source_label": parsed.source_label,
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        res = run_conversion(
            args.source,
            output=args.output,
            report=args.report,
            reference_pbn=args.reference_pbn,
        )
    except Exception as exc:  # noqa: BLE001 - surface a clean message for CLI users
        print(f"Error: {exc}")
        return 1
    return 1 if res["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
