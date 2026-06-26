from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

from PIL import Image, ImageTk

from src.core.utils import (
    resolve_game_root,
    discover_player_data_indices,
    read_player_config,
    write_player_config,
    read_nameplate_config,
    write_nameplate_config,
    resolve_nameplate_base_path,
    resolve_plate_image_path,
    resolve_skin_nameplate_dir,
)
from src.ui.styles import (
    BG, BG_ELEVATED, PANEL, PANEL_ALT, CARD, TEXT, MUTED, ACCENT,
    ACCENT_SOFT, BORDER, FONT_FAMILY,
    FONT_HEADING, FONT_BODY, FONT_SMALL, FONT_TINY,
)

CANVAS_W = 338
CANVAS_H = 86
PREVIEW_SCALE = 2.0
PREVIEW_W = int(CANVAS_W * PREVIEW_SCALE)
PREVIEW_H = int(CANVAS_H * PREVIEW_SCALE)

# パーツの切り出し範囲と実ピクセル範囲（実際のコンテンツ範囲、PIL用に right=X終了+1, bottom=Y終了+1）
# 各パーツ: (crop_box, content_box, canvas_pos, scale)
#   crop_box: NamePlate_Base からのフル切り出し範囲
#   content_box: 実ピクセル範囲（透過すべき余白を除いた実際の表示領域）
#   canvas_pos: 338x86 キャンバス上の配置位置
PARTS = {
    "A": {  # 白い画像（背面）
        "crop": (0, 0, 338, 86),
        "content": (4, 2, 334, 82),
        "pos": (142, 40),
        "size": (187, 41),
    },
    "B": {  # 赤1Pアイコン（前面）
        "crop": (10, 83, 80, 155),
        "content": (14, 87, 76, 151),
        "pos": (10, 5),
    },
    "C": {  # 長い黒画像（Pattern 2 用）
        "crop": (5, 160, 333, 206),
        "content": (13, 166, 325, 200),
        "pos": (5, 40),
    },
    "D": {  # 短い黒画像（背面・左）
        "crop": (5, 234, 149, 280),
        "content": (11, 240, 143, 274),
        "pos": (5, 40),
    },
}

# シンボル (rankType 0=銀, 1=金, 2=虹) 前面
SYMBOL_PARTS = {
    0: {"crop": (68, 315, 147, 366), "content": (75, 324, 138, 359), "pos": (73, 40)},
    1: {"crop": (68, 397, 147, 448), "content": (76, 406, 139, 441), "pos": (73, 40)},
    2: {"crop": (68, 479, 147, 528), "content": (76, 488, 139, 523), "pos": (73, 40)},
}

RANK_LABELS = {0: "Silver", 1: "Gold", 2: "Rainbow"}


def _crop_content(
    source: Image.Image,
    crop_box: tuple[int, int, int, int],
    content_box: tuple[int, int, int, int],
) -> tuple[Image.Image, int, int]:
    img = source.crop(content_box).convert("RGBA")
    ox = content_box[0] - crop_box[0]
    oy = content_box[1] - crop_box[1]
    return img, ox, oy


class PlayerDataEditor:
    def __init__(self, app, exe_path: Path, skin_folder: Path | None) -> None:
        self.app = app
        self.exe_path = exe_path
        self.skin_folder = skin_folder
        self.game_root = resolve_game_root(exe_path)

        self.window = tk.Toplevel(app)
        self.window.title("Player Data / NamePlate Editor")
        self.window.geometry("980x680")
        self.window.configure(bg=BG)
        self.window.transient(app)
        self.window.grab_set()

        self.current_index: int | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None

        self._build_ui()
        self._refresh_index_list()

    def _build_ui(self) -> None:
        header = ttk.Frame(self.window, padding=(16, 12, 16, 4))
        header.pack(fill="x")
        ttk.Label(
            header, text="Player Data / NamePlate Editor",
            font=(FONT_FAMILY, 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            header, text="Edit player configuration and nameplate settings.",
            foreground=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        selector_frame = tk.Frame(self.window, bg=BG)
        selector_frame.pack(fill="x", padx=16, pady=(8, 0))
        ttk.Label(selector_frame, text="PlayerData Index:").pack(side="left")
        self.index_combo = ttk.Combobox(
            selector_frame, state="readonly", width=12,
        )
        self.index_combo.pack(side="left", padx=(8, 0))
        ttk.Button(
            selector_frame, text="+ New",
            style="Ghost.TButton",
            command=self._add_new_index,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            selector_frame, text="Refresh",
            style="Ghost.TButton",
            command=self._refresh_index_list,
        ).pack(side="left", padx=(6, 0))

        self.index_combo.bind("<<ComboboxSelected>>", self._on_index_selected)

        body = tk.Frame(self.window, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(8, 8))

        left_frame = tk.Frame(body, bg=BG)
        left_frame.pack(side="left", fill="both", expand=True)

        self.notebook = ttk.Notebook(left_frame)
        self.notebook.pack(fill="both", expand=True)

        self._player_config_tab = ttk.Frame(self.notebook)
        self._nameplate_config_tab = ttk.Frame(self.notebook)
        self.notebook.add(self._player_config_tab, text="Player Config")
        self.notebook.add(self._nameplate_config_tab, text="NamePlate Config")

        self._build_player_config_tab()
        self._build_nameplate_config_tab()

        right_frame = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        right_frame.pack(side="right", fill="both", padx=(12, 0))

        self._build_preview(right_frame)

        btn_frame = tk.Frame(self.window, bg=BG)
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Button(
            btn_frame, text="Save",
            style="Accent.TButton",
            command=self._save,
        ).pack(side="left")
        ttk.Button(
            btn_frame, text="Cancel",
            style="Ghost.TButton",
            command=self.window.destroy,
        ).pack(side="left", padx=(8, 0))

    def _build_player_config_tab(self) -> None:
        outer = ttk.Frame(self._player_config_tab, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text="Player Configuration",
            font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w")

        fields = ttk.Frame(outer)
        fields.pack(fill="x", pady=(12, 0))

        self.pc_show_score = tk.BooleanVar(value=True)
        row1 = ttk.Frame(fields)
        row1.pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            row1, variable=self.pc_show_score,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0,
        ).pack(side="left")
        ttk.Label(row1, text="isShowScore (display score)").pack(side="left", padx=(6, 0))

        self.pc_save_score = tk.BooleanVar(value=True)
        row2 = ttk.Frame(fields)
        row2.pack(fill="x", pady=(0, 8))
        tk.Checkbutton(
            row2, variable=self.pc_save_score,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0,
        ).pack(side="left")
        ttk.Label(row2, text="isSaveScore (save score)").pack(side="left", padx=(6, 0))

        self.pc_score_panel = tk.IntVar(value=4)
        row3 = ttk.Frame(fields)
        row3.pack(fill="x", pady=(0, 8))
        ttk.Label(row3, text="songSelectScorePanelIndex:").pack(side="left")
        ttk.Spinbox(
            row3, from_=0, to=4, width=4,
            textvariable=self.pc_score_panel,
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            row3, text="0:Easy 1:Normal 2:Hard 3:Oni 4:Oni/Edit",
            foreground=MUTED, font=FONT_SMALL,
        ).pack(side="left", padx=(8, 0))

        hint = ttk.Label(
            outer, text="donchanType, isUsePuchiChara, puchiCharaType are ignored.",
            foreground=MUTED, font=FONT_TINY,
        )
        hint.pack(anchor="w", pady=(16, 0))

    def _build_nameplate_config_tab(self) -> None:
        outer = ttk.Frame(self._nameplate_config_tab, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer, text="NamePlate Configuration",
            font=(FONT_FAMILY, 12, "bold"),
        ).pack(anchor="w")

        fields = ttk.Frame(outer)
        fields.pack(fill="x", pady=(12, 0))

        self.np_name = tk.StringVar(value="")
        self.np_name.trace_add("write", lambda *_: self._update_preview())
        row1 = ttk.Frame(fields)
        row1.pack(fill="x", pady=(0, 6))
        ttk.Label(row1, text="name:").pack(side="left")
        ttk.Entry(row1, textvariable=self.np_name, width=30).pack(side="left", padx=(8, 0))

        self.np_title = tk.StringVar(value="")
        self.np_title.trace_add("write", lambda *_: self._update_preview())
        row2 = ttk.Frame(fields)
        row2.pack(fill="x", pady=(0, 6))
        ttk.Label(row2, text="title:").pack(side="left")
        ttk.Entry(row2, textvariable=self.np_title, width=30).pack(side="left", padx=(8, 0))

        self.np_rank = tk.StringVar(value="")
        self.np_rank.trace_add("write", lambda *_: self._update_preview())
        row3 = ttk.Frame(fields)
        row3.pack(fill="x", pady=(0, 6))
        ttk.Label(row3, text="rank:").pack(side="left")
        ttk.Entry(row3, textvariable=self.np_rank, width=30).pack(side="left", padx=(8, 0))

        self.np_is_rank_gold = tk.BooleanVar(value=False)
        self.np_is_rank_gold.trace_add("write", lambda *_: self._update_preview())
        row4 = ttk.Frame(fields)
        row4.pack(fill="x", pady=(0, 6))
        tk.Checkbutton(
            row4, variable=self.np_is_rank_gold,
            bg=BG, fg=TEXT, selectcolor=PANEL,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0,
        ).pack(side="left")
        ttk.Label(row4, text="isRankGold (gold rank)").pack(side="left", padx=(6, 0))

        self.np_plate_type = tk.IntVar(value=0)
        row5 = ttk.Frame(fields)
        row5.pack(fill="x", pady=(0, 6))
        ttk.Label(row5, text="namePlateType:").pack(side="left")
        ttk.Spinbox(
            row5, from_=0, to=999, width=6,
            textvariable=self.np_plate_type,
            command=self._on_plate_type_changed,
        ).pack(side="left", padx=(8, 0))

        self.np_rank_type = tk.IntVar(value=1)
        row6 = ttk.Frame(fields)
        row6.pack(fill="x", pady=(0, 6))
        ttk.Label(row6, text="rankType:").pack(side="left")
        rank_combo = ttk.Combobox(
            row6, state="readonly", width=10,
            values=["0: Silver", "1: Gold", "2: Rainbow"],
        )
        rank_combo.pack(side="left", padx=(8, 0))
        rank_combo.bind("<<ComboboxSelected>>", lambda e: self._on_rank_type_changed(rank_combo))

        self._rank_combo = rank_combo

    def _on_rank_type_changed(self, combo: ttk.Combobox) -> None:
        val = combo.get()
        if val.startswith("0"):
            self.np_rank_type.set(0)
        elif val.startswith("1"):
            self.np_rank_type.set(1)
        elif val.startswith("2"):
            self.np_rank_type.set(2)
        self._update_preview()

    def _on_plate_type_changed(self) -> None:
        self._update_preview()

    def _build_preview(self, parent: tk.Frame) -> None:
        self._preview_canvas = tk.Canvas(
            parent,
            width=PREVIEW_W + 4,
            height=PREVIEW_H + 4,
            bg=BG_ELEVATED,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        self._preview_canvas.pack(padx=12, pady=12)

    def _render_preview(self) -> Image.Image | None:
        if not self.skin_folder:
            return None
        base_path = resolve_nameplate_base_path(self.skin_folder)
        if not base_path.exists():
            return None

        source = Image.open(base_path).convert("RGBA")
        canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))

        # ── Layer 1 (Background) ──
        # D: short black on left (content only)
        d_img, dox, doy = _crop_content(source, PARTS["D"]["crop"], PARTS["D"]["content"])
        canvas.paste(d_img, (PARTS["D"]["pos"][0] + dox, PARTS["D"]["pos"][1] + doy), d_img)

        # A: white bg on right, scaled (content only, then scaled)
        a_info = PARTS["A"]
        a_img, aox, aoy = _crop_content(source, a_info["crop"], a_info["content"])
        a_cw = a_info["crop"][2] - a_info["crop"][0]
        a_ch = a_info["crop"][3] - a_info["crop"][1]
        sx = a_info["size"][0] / a_cw
        sy = a_info["size"][1] / a_ch
        a_img = a_img.resize(a_info["size"], Image.LANCZOS)
        ax = int(a_info["pos"][0] + aox * sx)
        ay = int(a_info["pos"][1] + aoy * sy)
        canvas.paste(a_img, (ax, ay), a_img)

        # ── Layer 2 (Overlay) ──
        # B: red 1P icon (content only)
        b_img, box, boy = _crop_content(source, PARTS["B"]["crop"], PARTS["B"]["content"])
        canvas.paste(b_img, (PARTS["B"]["pos"][0] + box, PARTS["B"]["pos"][1] + boy), b_img)

        # Rank symbol (content only)
        rank_type = self.np_rank_type.get()
        sym_info = SYMBOL_PARTS.get(rank_type)
        if sym_info:
            sym_img, sox, soy = _crop_content(source, sym_info["crop"], sym_info["content"])
            canvas.paste(sym_img, (sym_info["pos"][0] + sox, sym_info["pos"][1] + soy), sym_img)

        scaled = canvas.resize((PREVIEW_W, PREVIEW_H), Image.LANCZOS)
        return scaled

    def _update_preview(self) -> None:
        preview_img = self._render_preview()
        if preview_img is None:
            return
        self._preview_photo = ImageTk.PhotoImage(preview_img)
        self._preview_canvas.delete("all")
        cx = (PREVIEW_W + 4) // 2
        cy = (PREVIEW_H + 4) // 2
        self._preview_canvas.create_image(cx, cy, image=self._preview_photo, anchor="center")

    def _refresh_index_list(self) -> None:
        indices = discover_player_data_indices(self.exe_path)
        values = [str(i) for i in indices]
        self.index_combo["values"] = values
        if values:
            self.index_combo.set(values[-1])
            self._load_index(int(values[-1]))
        else:
            self.index_combo.set("")
            self._set_fields_enabled(False)

    def _add_new_index(self) -> None:
        indices = discover_player_data_indices(self.exe_path)
        new_idx = (indices[-1] + 1) if indices else 0
        self.index_combo.set(str(new_idx))
        self._load_index(new_idx)
        self._refresh_index_list()
        self.index_combo.set(str(new_idx))

    def _on_index_selected(self, _event=None) -> None:
        raw = self.index_combo.get()
        if raw and raw.isdigit():
            self._load_index(int(raw))

    def _load_index(self, index: int) -> None:
        self.current_index = index
        self._set_fields_enabled(True)

        pc = read_player_config(self.exe_path, index)
        self.pc_show_score.set(bool(pc.get("isShowScore", True)))
        self.pc_save_score.set(bool(pc.get("isSaveScore", True)))
        self.pc_score_panel.set(int(pc.get("songSelectScorePanelIndex", 4)))

        np = read_nameplate_config(self.exe_path, index)
        self.np_name.set(str(np.get("name", "")))
        self.np_title.set(str(np.get("title", "")))
        self.np_rank.set(str(np.get("rank", "")))
        self.np_is_rank_gold.set(bool(np.get("isRankGold", False)))
        self.np_plate_type.set(int(np.get("namePlateType", 0)))
        rt = int(np.get("rankType", 1))
        self.np_rank_type.set(rt)
        self._rank_combo.set(f"{rt}: {RANK_LABELS.get(rt, 'Gold')}")

        self._update_preview()

    def _set_fields_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for child in self._player_config_tab.winfo_children():
            _set_state_recursive(child, state)
        for child in self._nameplate_config_tab.winfo_children():
            _set_state_recursive(child, state)

    def _save(self) -> None:
        if self.current_index is None:
            return

        pc = {
            "isShowScore": self.pc_show_score.get(),
            "isSaveScore": self.pc_save_score.get(),
            "donchanType": 0,
            "isUsePuchiChara": False,
            "puchiCharaType": 0,
            "songSelectScorePanelIndex": self.pc_score_panel.get(),
        }
        np = {
            "name": self.np_name.get(),
            "title": self.np_title.get(),
            "rank": self.np_rank.get(),
            "isRankGold": self.np_is_rank_gold.get(),
            "namePlateType": self.np_plate_type.get(),
            "rankType": self.np_rank_type.get(),
        }

        try:
            write_player_config(self.exe_path, self.current_index, pc)
            write_nameplate_config(self.exe_path, self.current_index, np)
            messagebox.showinfo("Saved", f"PlayerData[{self.current_index}] saved.")
        except Exception as exc:
            messagebox.showerror("Save error", str(exc))


def _set_state_recursive(widget: tk.Widget, state: str) -> None:
    try:
        widget.configure(state=state)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        _set_state_recursive(child, state)
