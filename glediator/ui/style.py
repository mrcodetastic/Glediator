from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#0c1118",
        "panel": "#111923",
        "list_bg": "#0b1118",
        "input_bg": "#182330",
        "border": "#263343",
        "input_border": "#34475b",
        "text": "#dce5ef",
        "title": "#f4f7fb",
        "muted": "#93a8bd",
        "label": "#a8b8c9",
        "status_ok": "#67dfa3",
        "beacon": "#8ea0b4",
        "divider": "#39434e",
        "accent": "#2688e8",
        "accent_hover": "#409cf4",
        "selected": "#243a51",
        "handle": "#ffb84a",
        "menu_bg": "#cbd3dc",
        "menu_fg": "#1b2733",
        "menu_border": "#aab5c0",
        "menu_sel": "#b5c2cf",
        "menu_popup_bg": "#f5f7fa",
        "menu_popup_sel": "#d4e0ed",
    },
    "light": {
        "bg": "#eef2f6",
        "panel": "#ffffff",
        "list_bg": "#f7f9fc",
        "input_bg": "#ffffff",
        "border": "#cfd8e3",
        "input_border": "#b5c2d1",
        "text": "#1b2733",
        "title": "#0f1722",
        "muted": "#52657a",
        "label": "#334659",
        "status_ok": "#0e8a52",
        "beacon": "#52657a",
        "divider": "#cfd8e3",
        "accent": "#1d76d2",
        "accent_hover": "#2b87e5",
        "selected": "#d8e9fa",
        "handle": "#e68a00",
        "menu_bg": "#dfe5ec",
        "menu_fg": "#1b2733",
        "menu_border": "#c1cbd6",
        "menu_sel": "#c8d3df",
        "menu_popup_bg": "#ffffff",
        "menu_popup_sel": "#dce8f5",
    },
}


def build_stylesheet(theme: str = "dark") -> str:
    p = THEMES.get(theme, THEMES["dark"])
    return f"""
        QMainWindow, QWidget {{
            background:{p['bg']}; color:{p['text']};
            font-family:'Segoe UI', 'SF Pro Text', 'Ubuntu', 'Noto Sans', sans-serif; font-size:10pt;
        }}
        QMenuBar {{
            background:{p['menu_bg']}; color:{p['menu_fg']};
            border-bottom:1px solid {p['menu_border']}; padding:3px 8px;
        }}
        QMenuBar::item {{ background:transparent; color:{p['menu_fg']}; padding:5px 10px; border-radius:3px; }}
        QMenuBar::item:selected {{ background:{p['menu_sel']}; color:#102438; }}
        QMenu {{ background:{p['menu_popup_bg']}; color:{p['menu_fg']}; border:1px solid {p['menu_border']}; }}
        QMenu::item:selected {{ background:{p['menu_popup_sel']}; color:#102438; }}
        QLabel#appTitle {{ font-size:22pt; font-weight:700; letter-spacing:2px; color:{p['title']}; }}
        QLabel#subtitle {{ color:{p['muted']}; font-size:8pt; letter-spacing:2px; padding-left:10px; padding-top:6px; }}
        QFrame#headerDivider {{ color:{p['divider']}; background:{p['divider']}; max-height:1px; }}
        QLabel#previewTitle {{ color:{p['label']}; font-size:9pt; font-weight:600; letter-spacing:1px; }}
        QLabel#status {{ color:{p['status_ok']}; font-size:9pt; }}
        QLabel#beaconStatus {{ color:{p['beacon']}; font-size:8pt; border:0; background:transparent; }}
        QWidget#controlPanel {{ background:{p['panel']}; border:1px solid {p['border']}; border-radius:9px; }}
        QGroupBox {{
            background:{p['panel']}; border:1px solid {p['border']}; border-radius:9px;
            margin-top:10px; padding:10px; font-weight:600;
        }}
        QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 5px; color:{p['label']}; }}
        QListWidget {{ background:{p['list_bg']}; border:1px solid {p['border']}; border-radius:5px; padding:3px; }}
        QListWidget::item {{ padding:5px 6px; border-radius:3px; }}
        QListWidget::item:selected {{ background:{p['selected']}; color:{p['title']}; }}
        QComboBox, QSpinBox, QDoubleSpinBox {{
            background:{p['input_bg']}; border:1px solid {p['input_border']};
            border-radius:5px; padding:5px; min-width:68px;
        }}
        QLineEdit {{
            background:{p['input_bg']}; border:1px solid {p['input_border']}; border-radius:5px; padding:6px;
        }}
        QPushButton {{
            background:{p['accent']}; border:0; border-radius:5px; padding:8px 14px; color:white; font-weight:600;
        }}
        QPushButton:hover {{ background:{p['accent_hover']}; }}
        QPushButton:disabled {{ background:{p['border']}; color:{p['muted']}; }}
        QSlider::groove:horizontal {{ height:5px; background:{p['input_border']}; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:{p['handle']}; width:15px; margin:-6px 0; border-radius:7px; }}
        QStatusBar {{ color:{p['beacon']}; border:0; }}
        QStatusBar::item {{ border:0; }}
    """
