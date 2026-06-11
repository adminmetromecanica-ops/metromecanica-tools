"""
╔══════════════════════════════════════════════════════════════════╗
║   ESTUDIO DE DERIVA — PESAS PATRÓN M1   NMP 004:2007            ║
║   Metromecanica — Metrología y Calibración SAC                  ║
║   Ingreso de certificados · Análisis de tendencia · u(δm_Dcr)  ║
╚══════════════════════════════════════════════════════════════════╝
  Dependencias: pip install matplotlib numpy scipy openpyxl pandas
  Ejecutar    : python deriva_patron_M1.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, math
from datetime import datetime
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from scipy import stats
import pandas as pd

# ── Constantes ─────────────────────────────────────────────────────
APP_TITLE   = "Deriva Patrón M1  ·  Metromecanica"
JSON_FILE   = "historial_deriva_M1.json"
EXPORT_FILE = "reporte_deriva_M1.xlsx"

DENOMINATIONS = [
    "1 g","2 g","5 g","10 g","20 g","50 g",
    "100 g","200 g","500 g",
    "1 kg","2 kg","5 kg","10 kg","20 kg",
    "15 kg","25 kg",
]

# ── EMP M1 según OIML R111 (mg) — tabla corregida ──────────────────
# Fuente: OIML R 111-1:2004 Tabla B.5
EMP_M1 = {
    "1 g":   1.0,
    "2 g":   1.2,
    "5 g":   2.5,
    "10 g":  2.0,
    "20 g":  2.5,
    "50 g":  3.0,
    "100 g": 5.0,
    "200 g": 10.0,
    "500 g": 25.0,
    "1 kg":  50.0,
    "2 kg":  100.0,
    "5 kg":  250.0,
    "10 kg": 500.0,
    "20 kg": 1000.0,
    "15 kg": 750.0,
    "25 kg": 1250.0,
}

# ── Paleta ──────────────────────────────────────────────────────────
C_BG       = "#F8F8F6"
C_PANEL    = "#FFFFFF"
C_HEADER   = "#1A3A5C"
C_ACCENT   = "#185FA5"
C_ACCENT2  = "#B5D4F4"
C_BORDE    = "#D3D1C7"
C_TEXTO    = "#2C2C2A"
C_MUTED    = "#888780"
C_ROJO     = "#A32D2D"
C_VERDE    = "#3B6D11"
C_NARANJA  = "#BA7517"
C_FILA_ALT = "#F1EFE8"

FONT_BASE  = ("Segoe UI", 9)
FONT_BOLD  = ("Segoe UI", 9, "bold")
FONT_TITLE = ("Segoe UI", 11, "bold")
FONT_MONO  = ("Consolas", 9)
FONT_SMALL = ("Segoe UI", 8)

# ── Formato numérico con coma decimal ──────────────────────────────
def fmt(valor, dec=6):
    """Número con signo y coma decimal."""
    return f"{valor:+.{dec}f}".replace(".", ",")

def fmtp(valor, dec=6):
    """Número positivo con coma decimal."""
    return f"{valor:.{dec}f}".replace(".", ",")

# ── Persistencia ────────────────────────────────────────────────────
def cargar_historial():
    if Path(JSON_FILE).exists():
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {d: [] for d in DENOMINATIONS}

def guardar_historial(data):
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── Cálculos ────────────────────────────────────────────────────────
def fecha_a_año(fecha_str):
    d   = datetime.strptime(fecha_str, "%Y-%m-%d")
    ini = datetime(d.year, 1, 1)
    fin = datetime(d.year + 1, 1, 1)
    return d.year + (d - ini).days / (fin - ini).days

def calcular_deriva(registros):
    validos = [r for r in registros if r.get("fecha") and r.get("delta") is not None]
    if len(validos) < 2:
        return None
    años   = np.array([fecha_a_año(r["fecha"]) for r in validos])
    deltas = np.array([float(r["delta"]) for r in validos])
    slope, intercept, r, p, se = stats.linregress(años, deltas)
    r2      = r ** 2
    u_drift = abs(slope) / math.sqrt(3)
    u_mcr   = float(validos[-1]["U"]) / float(validos[-1]["k"]) \
              if validos[-1].get("U") else None
    año_max = años.max()
    return {
        "años": años, "deltas": deltas,
        "slope": slope, "intercept": intercept,
        "r2": r2, "u_drift": u_drift, "u_mcr": u_mcr,
        "año_max": año_max, "año_min": años.min(),
        "n": len(validos),
        "año_futuro": año_max + 1.0,
        "proj_val":   slope * (año_max + 1.0) + intercept,
    }

def tendencia_label(slope):
    if abs(slope) < 1e-4:
        return "≈ Estable", C_ACCENT
    return ("▲ Ganancia de masa", C_ROJO) if slope > 0 else ("▼ Pérdida de masa", C_VERDE)

def eval_emp(delta, U_exp, emp):
    """Semáforo vs EMP. Devuelve (texto, color, delta+U, delta-U)."""
    lim_s = delta + U_exp
    lim_i = delta - U_exp
    peor  = max(abs(lim_s), abs(lim_i))
    if peor >= emp:
        return "✘ RIESGO — supera EMP con incertidumbre", C_ROJO,  lim_s, lim_i
    elif peor >= emp * 0.75:
        return "⚠ ALERTA — próximo al EMP",               C_NARANJA, lim_s, lim_i
    else:
        return "✔ CONFORME — margen amplio",               C_VERDE,  lim_s, lim_i

# ═══════════════════════════════════════════════════════════════════
#  APLICACIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════
class App:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.configure(bg=C_BG)
        self.root.geometry("1380x840")
        self.root.minsize(1150, 720)

        self.historial    = cargar_historial()
        self.denom_actual = tk.StringVar(value=DENOMINATIONS[0])
        for d in DENOMINATIONS:
            if d not in self.historial:
                self.historial[d] = []

        self._build_ui()
        self._cargar_denom(DENOMINATIONS[0])

    # ── Construcción UI ──────────────────────────────────────────
    def _build_ui(self):
        # Barra superior
        hdr = tk.Frame(self.root, bg=C_HEADER, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="DERIVA PESAS PATRÓN M1",
                 font=("Segoe UI", 13, "bold"), bg=C_HEADER, fg="white"
                 ).pack(side="left", padx=18, pady=12)
        tk.Label(hdr,
                 text="NMP 004:2007  ·  Metromecanica — Metrología y Calibración SAC",
                 font=("Segoe UI", 9), bg=C_HEADER, fg="#B5D4F4"
                 ).pack(side="left", padx=4)
        tk.Button(hdr, text="⬇  Exportar Excel", font=FONT_BOLD,
                  bg="#0C447C", fg="white", relief="flat", padx=12,
                  command=self._exportar_excel
                  ).pack(side="right", padx=16, pady=10)

        main = tk.Frame(self.root, bg=C_BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(main, bg=C_BG, width=418)
        left.pack(side="left", fill="y", padx=(0, 6))
        left.pack_propagate(False)

        right = tk.Frame(main, bg=C_BG)
        right.pack(side="left", fill="both", expand=True)

        self._build_left(left)
        self._build_right(right)

    # ── Panel izquierdo ──────────────────────────────────────────
    def _build_left(self, parent):
        # Selector denominación
        sel = tk.LabelFrame(parent, text="  Denominación  ",
                            bg=C_PANEL, fg=C_HEADER, font=FONT_BOLD,
                            relief="groove", bd=1)
        sel.pack(fill="x", pady=(0, 5))
        for i, d in enumerate(DENOMINATIONS):
            r, c = divmod(i, 4)
            tk.Radiobutton(sel, text=d, variable=self.denom_actual, value=d,
                           command=lambda v=d: self._cargar_denom(v),
                           bg=C_PANEL, fg=C_TEXTO, selectcolor=C_ACCENT2,
                           font=FONT_SMALL, padx=4
                           ).grid(row=r, column=c, sticky="w", padx=6, pady=2)

        # Formulario de ingreso
        form = tk.LabelFrame(parent, text="  Agregar / editar certificado  ",
                             bg=C_PANEL, fg=C_HEADER, font=FONT_BOLD,
                             relief="groove", bd=1)
        form.pack(fill="x", pady=(0, 5))
        campos = [
            ("Fecha certificado", "AAAA-MM-DD"),
            ("δm_cr (mg)",        "ej. +0,45"),
            ("U(m_cr) (mg)",      "ej. 0,30"),
            ("Factor k",          "2"),
            ("N° certificado",    "opcional"),
        ]
        self.form_vars    = {}
        self._form_entries = {}
        for i, (lbl, ph) in enumerate(campos):
            tk.Label(form, text=lbl, bg=C_PANEL, fg=C_TEXTO,
                     font=FONT_BASE, anchor="w"
                     ).grid(row=i, column=0, sticky="w", padx=10, pady=3)
            var = tk.StringVar(value=ph)
            self.form_vars[lbl] = var
            e = tk.Entry(form, textvariable=var, font=FONT_MONO, width=18,
                         bg=C_FILA_ALT, relief="flat",
                         highlightthickness=1, highlightbackground=C_BORDE,
                         highlightcolor=C_ACCENT, fg=C_MUTED)
            e.grid(row=i, column=1, padx=10, pady=3, sticky="ew")
            self._form_entries[lbl] = e
            e.bind("<FocusIn>",
                   lambda ev, v=var, p=ph, en=e: self._ph_in(ev, v, p, en))
            e.bind("<FocusOut>",
                   lambda ev, v=var, p=ph, en=e: self._ph_out(ev, v, p, en))
        form.columnconfigure(1, weight=1)
        br = tk.Frame(form, bg=C_PANEL)
        br.grid(row=len(campos), column=0, columnspan=2,
                pady=8, padx=10, sticky="ew")
        tk.Button(br, text="+ Agregar", font=FONT_BOLD,
                  bg=C_ACCENT, fg="white", relief="flat", padx=12,
                  command=self._agregar_registro
                  ).pack(side="left", padx=(0, 6))
        tk.Button(br, text="Limpiar", font=FONT_BASE,
                  bg=C_BG, fg=C_MUTED, relief="flat", padx=8,
                  command=self._limpiar_form
                  ).pack(side="left")

        # Tabla historial
        tf = tk.LabelFrame(parent, text="  Historial de certificados  ",
                           bg=C_PANEL, fg=C_HEADER, font=FONT_BOLD,
                           relief="groove", bd=1)
        tf.pack(fill="both", expand=True, pady=(0, 5))
        cols_t = ("Fecha", "δm_cr mg", "U mg", "k", "Certif.")
        self.tabla = ttk.Treeview(tf, columns=cols_t, show="headings",
                                  height=9, selectmode="browse")
        for col, w in zip(cols_t, [90, 88, 75, 34, 95]):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=w, anchor="center")
        sc = ttk.Scrollbar(tf, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=sc.set)
        self.tabla.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        sc.pack(side="right", fill="y", pady=4)
        self.tabla.bind("<<TreeviewSelect>>", self._seleccionar_fila)

        bbt = tk.Frame(parent, bg=C_BG)
        bbt.pack(fill="x", pady=2)
        tk.Button(bbt, text="✎ Editar selec.", font=FONT_SMALL,
                  bg=C_PANEL, fg=C_TEXTO, relief="flat", bd=1,
                  command=self._editar_registro).pack(side="left", padx=(0, 4))
        tk.Button(bbt, text="✕ Eliminar selec.", font=FONT_SMALL,
                  bg=C_PANEL, fg=C_ROJO, relief="flat", bd=1,
                  command=self._eliminar_registro).pack(side="left")

        # Resultados numéricos + EMP
        rf = tk.LabelFrame(parent, text="  Resultados de deriva  ",
                           bg=C_PANEL, fg=C_HEADER, font=FONT_BOLD,
                           relief="groove", bd=1)
        rf.pack(fill="x")
        self.lbl_slope  = self._mrow(rf, "Deriva (mg/año)",     "—", 0)
        self.lbl_udrift = self._mrow(rf, "u(δm_Dcr) mg",        "—", 1)
        self.lbl_umcr   = self._mrow(rf, "u(m_cr) último mg",   "—", 2)
        self.lbl_r2     = self._mrow(rf, "R²  (bondad ajuste)", "—", 3)
        self.lbl_tend   = self._mrow(rf, "Tendencia",            "—", 4)
        self.lbl_proj   = self._mrow(rf, "Proyección +1 año",   "—", 5)
        self.lbl_n      = self._mrow(rf, "N certificados",       "—", 6)
        ttk.Separator(rf, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", padx=8, pady=3)
        tk.Label(rf, text="EVALUACIÓN EMP  —  OIML R111 / NMP 004:2007",
                 bg=C_PANEL, fg=C_HEADER, font=FONT_BOLD
                 ).grid(row=8, column=0, columnspan=2,
                        sticky="w", padx=10, pady=(0, 2))
        self.lbl_emp        = self._mrow(rf, "EMP M1 (±mg)", "—",  9)
        self.lbl_emp_estado = self._mrow(rf, "Estado",        "—", 10)
        self.lbl_emp_margen = self._mrow(rf, "δ+U  /  δ−U",  "—", 11)

    def _mrow(self, parent, label, val, row):
        tk.Label(parent, text=label, bg=C_PANEL, fg=C_MUTED,
                 font=FONT_SMALL, anchor="w"
                 ).grid(row=row, column=0, sticky="w", padx=10, pady=2)
        lbl = tk.Label(parent, text=val, bg=C_PANEL, fg=C_TEXTO,
                       font=FONT_MONO, anchor="e")
        lbl.grid(row=row, column=1, sticky="e", padx=10, pady=2)
        parent.columnconfigure(1, weight=1)
        return lbl

    # ── Panel derecho — 3 pestañas ───────────────────────────────
    def _build_right(self, parent):
        top = tk.Frame(parent, bg=C_BG)
        top.pack(fill="x", pady=(0, 4))
        self.lbl_titulo = tk.Label(top, text="Gráfico de deriva",
                                   font=FONT_TITLE, bg=C_BG, fg=C_HEADER)
        self.lbl_titulo.pack(side="left")
        self.lbl_sub = tk.Label(top, text="", font=FONT_SMALL,
                                bg=C_BG, fg=C_MUTED)
        self.lbl_sub.pack(side="left", padx=8)

        # Estilo pestañas
        s = ttk.Style()
        s.configure("D.TNotebook",     background=C_BG,    borderwidth=0)
        s.configure("D.TNotebook.Tab", background="#DFE0DA", foreground=C_TEXTO,
                    font=FONT_BOLD, padding=[16, 7])
        s.map("D.TNotebook.Tab",
              background=[("selected", C_HEADER)],
              foreground=[("selected", "white")])

        self.nb = ttk.Notebook(parent, style="D.TNotebook")
        self.nb.pack(fill="both", expand=True)
        self.nb.bind("<<NotebookTabChanged>>",
                     lambda e: self._redraw_current_tab())

        def _make_tab(label):
            f = tk.Frame(self.nb, bg=C_BG)
            self.nb.add(f, text=label)
            fig = Figure(figsize=(9.5, 5.8), dpi=96, facecolor=C_BG)
            cv  = FigureCanvasTkAgg(fig, master=f)
            cv.get_tk_widget().pack(fill="both", expand=True)
            return fig, cv

        self.fig1, self.cv1 = _make_tab("  📈  Corrección & Regresión  ")
        self.fig2, self.cv2 = _make_tab("  📊  Deriva entre calibraciones  ")
        self.fig3, self.cv3 = _make_tab("  🎯  Evaluación EMP M1  ")

    # ── Redibujado por pestaña activa ────────────────────────────
    def _redraw_current_tab(self):
        idx   = self.nb.index(self.nb.select())
        denom = self.denom_actual.get()
        res   = calcular_deriva(self.historial.get(denom, []))
        regs  = [r for r in self.historial.get(denom, [])
                 if r.get("fecha") and r.get("delta") is not None]
        {0: self._draw_tab1,
         1: self._draw_tab2,
         2: self._draw_tab3}[idx](denom, res, regs)

    # ── Tab 1: Corrección convencional + regresión ───────────────
    def _draw_tab1(self, denom, res, regs):
        self.fig1.clf()
        ax = self.fig1.add_subplot(111)
        ax.set_facecolor(C_PANEL)
        self.fig1.subplots_adjust(top=0.88, bottom=0.10, left=0.09, right=0.97)

        if res is None:
            self._sin_datos(ax, self.cv1); return

        años   = res["años"]
        deltas = res["deltas"]
        tc = (C_ROJO  if res["slope"] > 1e-4 else
              C_VERDE if res["slope"] < -1e-4 else C_ACCENT)

        # Barras ±u(m_cr) = U/k
        for i, reg in enumerate(regs):
            if reg.get("U") and reg.get("k"):
                u = float(reg["U"]) / float(reg["k"])
                ax.errorbar(años[i], deltas[i], yerr=u,
                            fmt="none", color=C_ACCENT2, capsize=7,
                            linewidth=1.5, zorder=3)

        # Puntos δm_cr
        ax.scatter(años, deltas, color=C_ACCENT, s=70, zorder=5,
                   label="δm_cr certificado",
                   edgecolors=C_HEADER, linewidths=0.6)

        # Línea de regresión extendida a +1 año
        x_ext  = np.linspace(res["año_min"] - 0.5, res["año_futuro"] + 0.3, 400)
        y_line = res["slope"] * x_ext + res["intercept"]
        ax.plot(x_ext, y_line, color=tc, linewidth=2.0,
                linestyle="--", alpha=0.85, label="Regresión lineal", zorder=4)

        # Punto proyección
        ax.scatter(res["año_futuro"], res["proj_val"],
                   color=tc, marker="D", s=75, zorder=6,
                   label=f"Proyección +1a: {fmt(res['proj_val'], 4)} mg",
                   edgecolors=C_TEXTO, linewidths=0.7)

        # Línea vertical en último certificado
        ax.axvline(res["año_max"], color=C_BORDE, linewidth=0.8, linestyle=":")

        # Banda ±u_drift sombreada
        ax.fill_between(x_ext, y_line - res["u_drift"], y_line + res["u_drift"],
                        alpha=0.10, color=tc, label="Banda ±u_drift")

        tend_txt, _ = tendencia_label(res["slope"])
        ax.set_title(
            f"Corrección convencional — {denom}     "
            f"Deriva: {fmt(res['slope'], 5)} mg/año   "
            f"R²: {fmtp(res['r2'], 4)}   {tend_txt}",
            fontsize=9, fontweight="bold", color=C_HEADER, pad=10)
        ax.set_xlabel("Año", fontsize=9, color=C_MUTED)
        ax.set_ylabel("δm_cr (mg)", fontsize=9, color=C_MUTED)
        ax.legend(fontsize=8.5, loc="best", framealpha=0.9)
        ax.grid(True, color="#E8E6DF", linewidth=0.5)
        ax.tick_params(labelsize=8, colors=C_MUTED)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{v:+.3f}".replace(".", ",")))
        self.cv1.draw()

    # ── Tab 2: Deriva puntual entre calibraciones ────────────────
    def _draw_tab2(self, denom, res, regs):
        self.fig2.clf()
        ax = self.fig2.add_subplot(111)
        ax.set_facecolor(C_PANEL)
        self.fig2.subplots_adjust(top=0.88, bottom=0.18, left=0.10, right=0.97)

        if res is None or len(res["años"]) < 2:
            self._sin_datos(ax, self.cv2); return

        años   = res["años"]
        deltas = res["deltas"]
        diffs  = np.diff(deltas) / np.diff(años)   # mg/año por intervalo

        colores = [C_ROJO if d > 0 else C_VERDE for d in diffs]
        bars = ax.bar(range(len(diffs)), diffs, color=colores,
                      width=0.55, alpha=0.78,
                      edgecolor=C_PANEL, linewidth=0.5)

        ax.axhline(res["slope"], color=C_ACCENT, linewidth=1.8,
                   linestyle="--",
                   label=f"Deriva media (regr.): {fmt(res['slope'], 5)} mg/año")
        ax.axhline(0, color=C_BORDE, linewidth=0.8)

        etiq = [f"{r1['fecha'][:7]}\n→ {r2['fecha'][:7]}"
                for r1, r2 in zip(regs[:-1], regs[1:])]
        ax.set_xticks(range(len(diffs)))
        ax.set_xticklabels(etiq, fontsize=8, color=C_MUTED)

        for bar, val in zip(bars, diffs):
            off = abs(val) * 0.05 + 0.001
            ax.text(bar.get_x() + bar.get_width() / 2,
                    val + (off if val >= 0 else -off),
                    fmt(val, 4), ha="center",
                    va="bottom" if val >= 0 else "top",
                    fontsize=8.5, color=C_TEXTO, fontweight="bold")

        ax.set_title(
            f"Deriva entre calibraciones consecutivas — {denom}     "
            f"Deriva media: {fmt(res['slope'], 5)} mg/año",
            fontsize=9, fontweight="bold", color=C_HEADER, pad=10)
        ax.set_ylabel("Deriva puntual (mg/año)", fontsize=9, color=C_MUTED)
        ax.legend(fontsize=8.5, framealpha=0.9)
        ax.grid(True, color="#E8E6DF", linewidth=0.5, axis="y")
        ax.tick_params(labelsize=8, colors=C_MUTED)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{v:+.4f}".replace(".", ",")))
        self.cv2.draw()

    # ── Tab 3: Evaluación EMP M1 ─────────────────────────────────
    def _draw_tab3(self, denom, res, regs):
        self.fig3.clf()
        ax = self.fig3.add_subplot(111)
        ax.set_facecolor(C_PANEL)
        self.fig3.subplots_adjust(top=0.87, bottom=0.13, left=0.10, right=0.96)

        emp = EMP_M1.get(denom)
        if not regs or emp is None:
            self._sin_datos(ax, self.cv3); return

        n_pts = len(regs) + (1 if res else 0)

        # Zonas EMP
        ax.axhline( emp, color="#AA0000", linewidth=2.2, linestyle="-", zorder=2,
                    label=f"EMP M1: ±{fmtp(emp, 3)} mg")
        ax.axhline(-emp, color="#AA0000", linewidth=2.2, linestyle="-", zorder=2)
        ax.axhspan(-emp, emp, alpha=0.06, color="#22AA22", label="Zona conforme")
        ax.axhspan( emp * 0.75,  emp,  alpha=0.10, color=C_NARANJA)
        ax.axhspan(-emp, -emp * 0.75, alpha=0.10, color=C_NARANJA,
                   label="Zona alerta (75–100% EMP)")

        # Texto EMP en el margen
        ax.text(n_pts - 0.1,  emp * 1.03, f"+{fmtp(emp, 3)} mg",
                fontsize=8.5, color="#AA0000", va="bottom", ha="right")
        ax.text(n_pts - 0.1, -emp * 1.03, f"−{fmtp(emp, 3)} mg",
                fontsize=8.5, color="#AA0000", va="top", ha="right")

        fechas_lbl = []
        for i, reg in enumerate(regs):
            delta = float(reg["delta"])
            U_exp = float(reg["U"]) if reg.get("U") else 0.0
            u_mcr = U_exp / float(reg["k"]) if reg.get("k") else U_exp

            peor  = max(abs(delta + U_exp), abs(delta - U_exp))
            c_pt  = (C_ROJO   if peor >= emp else
                     C_NARANJA if peor >= emp * 0.75 else C_VERDE)

            # Barra ±U(m_cr) expandida
            ax.errorbar(i, delta, yerr=U_exp,
                        fmt="o", color=c_pt, capsize=8,
                        linewidth=1.6, markersize=9, zorder=5,
                        markeredgecolor=C_TEXTO, markeredgewidth=0.5)

            off = U_exp + emp * 0.04
            ax.text(i, delta + (off if delta >= 0 else -off),
                    fmt(delta, 3), ha="center",
                    va="bottom" if delta >= 0 else "top",
                    fontsize=8.5, color=c_pt, fontweight="bold")

            fechas_lbl.append(reg["fecha"][:7])

        # Proyección +1 año
        if res:
            x_p = len(regs)
            ax.scatter(x_p, res["proj_val"],
                       marker="D", color=C_NARANJA, s=80, zorder=6,
                       label=f"Proyección +1a: {fmt(res['proj_val'], 3)} mg",
                       edgecolors=C_TEXTO, linewidths=0.7)
            ax.errorbar(x_p, res["proj_val"], yerr=res["u_drift"],
                        fmt="none", color=C_NARANJA, capsize=6,
                        linewidth=1.4, zorder=5)
            fechas_lbl.append("Proy.\n+1a")

        ax.set_xticks(range(len(fechas_lbl)))
        ax.set_xticklabels(fechas_lbl, fontsize=8.5, color=C_MUTED)
        ax.set_xlim(-0.7, len(fechas_lbl) - 0.3)
        ax.axhline(0, color=C_BORDE, linewidth=0.6)

        # Estado semáforo en título
        estado, col_e = "—", C_MUTED
        if regs and regs[-1].get("delta") is not None and regs[-1].get("U"):
            d_u   = float(regs[-1]["delta"])
            U_u   = float(regs[-1]["U"])
            estado, col_e, _, _ = eval_emp(d_u, U_u, emp)

        ax.set_title(
            f"Evaluación EMP — clase M1   {denom}   EMP: ±{fmtp(emp, 3)} mg\n"
            f"{estado}",
            fontsize=9, fontweight="bold", color=col_e, pad=8)
        ax.set_ylabel("δm_cr (mg)", fontsize=9, color=C_MUTED)
        ax.legend(fontsize=8.5, loc="upper right", framealpha=0.9)
        ax.grid(True, color="#E8E6DF", linewidth=0.5, axis="y")
        ax.tick_params(labelsize=8, colors=C_MUTED)
        for sp in ["top", "right"]:
            ax.spines[sp].set_visible(False)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{v:+.3f}".replace(".", ",")))
        self.cv3.draw()

    def _sin_datos(self, ax, cv):
        ax.text(0.5, 0.5, "Sin datos suficientes\n(mínimo 2 certificados)",
                ha="center", va="center", fontsize=13, color=C_MUTED,
                transform=ax.transAxes)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        cv.draw()

    # ── Carga denominación ────────────────────────────────────────
    def _cargar_denom(self, denom):
        self.denom_actual.set(denom)
        self._refrescar_tabla()
        self._refrescar_resultados()
        self.lbl_titulo.config(text=f"Deriva — {denom}")
        self._redraw_current_tab()

    def _refrescar_tabla(self):
        for row in self.tabla.get_children():
            self.tabla.delete(row)
        denom = self.denom_actual.get()
        for i, reg in enumerate(self.historial.get(denom, [])):
            tag = "alt" if i % 2 else ""
            self.tabla.insert("", "end", iid=str(i), tag=tag, values=(
                reg.get("fecha", ""),
                fmt(float(reg["delta"]), 5) if reg.get("delta") is not None else "",
                fmtp(float(reg["U"]), 5)    if reg.get("U") else "",
                reg.get("k", "2"),
                reg.get("certif", ""),
            ))
        self.tabla.tag_configure("alt", background=C_FILA_ALT)

    def _refrescar_resultados(self):
        denom = self.denom_actual.get()
        res   = calcular_deriva(self.historial.get(denom, []))
        emp   = EMP_M1.get(denom)

        self.lbl_emp.config(
            text=f"±{fmtp(emp, 3)} mg" if emp else "—", fg=C_TEXTO)

        if res is None:
            for lbl in [self.lbl_slope, self.lbl_udrift, self.lbl_umcr,
                        self.lbl_r2, self.lbl_tend, self.lbl_proj, self.lbl_n,
                        self.lbl_emp_estado, self.lbl_emp_margen]:
                lbl.config(text="—", fg=C_MUTED)
            self.lbl_sub.config(text="Ingrese al menos 2 certificados")
            return

        tend_txt, tc = tendencia_label(res["slope"])
        self.lbl_slope.config(  text=f"{fmt(res['slope'], 6)} mg/año",  fg=tc)
        self.lbl_udrift.config( text=f"{fmtp(res['u_drift'], 6)} mg",   fg=C_TEXTO)
        self.lbl_umcr.config(
            text=f"{fmtp(res['u_mcr'], 6)} mg" if res["u_mcr"] else "—", fg=C_TEXTO)
        self.lbl_r2.config(     text=fmtp(res["r2"], 5),                 fg=C_TEXTO)
        self.lbl_tend.config(   text=tend_txt,                            fg=tc)
        self.lbl_proj.config(
            text=f"{fmt(res['proj_val'], 5)} mg  (año {res['año_futuro']:.1f})",
            fg=C_NARANJA)
        self.lbl_n.config(text=str(res["n"]), fg=C_TEXTO)

        regs = [r for r in self.historial[denom] if r.get("delta") is not None]
        if emp and regs and regs[-1].get("U"):
            d_u   = float(regs[-1]["delta"])
            U_u   = float(regs[-1]["U"])
            estado, col_e, sup, inf = eval_emp(d_u, U_u, emp)
            self.lbl_emp_estado.config(text=estado, fg=col_e)
            self.lbl_emp_margen.config(
                text=f"{fmt(sup, 3)}  /  {fmt(inf, 3)}", fg=C_MUTED)
        else:
            self.lbl_emp_estado.config(text="—", fg=C_MUTED)
            self.lbl_emp_margen.config(text="—", fg=C_MUTED)

        self.lbl_sub.config(
            text=f"Deriva: {fmt(res['slope'], 6)} mg/año  ·  "
                 f"u(δm_Dcr): {fmtp(res['u_drift'], 6)} mg  ·  "
                 f"R²: {fmtp(res['r2'], 4)}  ·  {tend_txt}")

    # ── Formulario helpers ────────────────────────────────────────
    def _ph_in(self, ev, var, ph, entry):
        if var.get() == ph:
            entry.delete(0, "end")
            entry.config(fg=C_TEXTO)

    def _ph_out(self, ev, var, ph, entry):
        if var.get().strip() == "":
            entry.insert(0, ph)
            entry.config(fg=C_MUTED)

    def _limpiar_form(self):
        phs = {
            "Fecha certificado": "AAAA-MM-DD",
            "δm_cr (mg)":        "ej. +0,45",
            "U(m_cr) (mg)":      "ej. 0,30",
            "Factor k":          "2",
            "N° certificado":    "opcional",
        }
        for lbl, var in self.form_vars.items():
            var.set(phs[lbl])
            self._form_entries[lbl].config(fg=C_MUTED)

    def _get_form(self):
        phs = {"AAAA-MM-DD", "ej. +0,45", "ej. 0,30", "2", "opcional"}
        return {k: ("" if v.get().strip() in phs else v.get().strip())
                for k, v in self.form_vars.items()}

    def _parse_num(self, s):
        return float(s.replace(",", "."))

    def _validar(self, vals):
        if not vals["Fecha certificado"]:
            messagebox.showwarning("Campo requerido",
                                   "Ingresa la fecha (AAAA-MM-DD)."); return False
        try:
            datetime.strptime(vals["Fecha certificado"], "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Formato incorrecto",
                                 "Fecha debe ser AAAA-MM-DD."); return False
        if not vals["δm_cr (mg)"]:
            messagebox.showwarning("Campo requerido",
                                   "Ingresa δm_cr en mg."); return False
        try:
            self._parse_num(vals["δm_cr (mg)"])
        except ValueError:
            messagebox.showerror("Valor inválido",
                                 "δm_cr debe ser número."); return False
        return True

    # ── CRUD ──────────────────────────────────────────────────────
    def _build_reg(self, vals):
        return {
            "fecha":  vals["Fecha certificado"],
            "delta":  self._parse_num(vals["δm_cr (mg)"]),
            "U":      self._parse_num(vals["U(m_cr) (mg)"]) if vals["U(m_cr) (mg)"] else None,
            "k":      self._parse_num(vals["Factor k"]) if vals["Factor k"] else 2.0,
            "certif": vals["N° certificado"],
        }

    def _refresh_all(self):
        self._refrescar_tabla()
        self._refrescar_resultados()
        self._redraw_current_tab()

    def _agregar_registro(self):
        vals = self._get_form()
        if not self._validar(vals): return
        denom = self.denom_actual.get()
        self.historial[denom].append(self._build_reg(vals))
        self.historial[denom].sort(key=lambda r: r["fecha"])
        guardar_historial(self.historial)
        self._limpiar_form()
        self._refresh_all()

    def _seleccionar_fila(self, _=None):
        sel = self.tabla.selection()
        if not sel: return
        reg = self.historial[self.denom_actual.get()][int(sel[0])]
        self.form_vars["Fecha certificado"].set(reg.get("fecha", ""))
        self.form_vars["δm_cr (mg)"].set(
            str(reg.get("delta", "")).replace(".", ","))
        self.form_vars["U(m_cr) (mg)"].set(
            str(reg.get("U", "")).replace(".", ",") if reg.get("U") else "")
        self.form_vars["Factor k"].set(str(reg.get("k", "2")))
        self.form_vars["N° certificado"].set(reg.get("certif", ""))
        for e in self._form_entries.values():
            e.config(fg=C_TEXTO)

    def _editar_registro(self):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showinfo("Sin selección",
                                "Selecciona una fila para editar."); return
        vals = self._get_form()
        if not self._validar(vals): return
        denom = self.denom_actual.get()
        self.historial[denom][int(sel[0])] = self._build_reg(vals)
        self.historial[denom].sort(key=lambda r: r["fecha"])
        guardar_historial(self.historial)
        self._limpiar_form()
        self._refresh_all()

    def _eliminar_registro(self):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showinfo("Sin selección",
                                "Selecciona una fila para eliminar."); return
        denom = self.denom_actual.get()
        reg   = self.historial[denom][int(sel[0])]
        if messagebox.askyesno("Confirmar",
                               f"¿Eliminar registro del {reg.get('fecha', '')}?"):
            del self.historial[denom][int(sel[0])]
            guardar_historial(self.historial)
            self._limpiar_form()
            self._refresh_all()

    # ── Exportar Excel ────────────────────────────────────────────
    def _exportar_excel(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
            initialfile=EXPORT_FILE, title="Guardar reporte de deriva")
        if not path: return

        with pd.ExcelWriter(path, engine="openpyxl") as writer:

            # Hoja 1 — Resumen
            filas = []
            for d in DENOMINATIONS:
                res = calcular_deriva(self.historial.get(d, []))
                emp = EMP_M1.get(d, "")
                regs = [r for r in self.historial.get(d, []) if r.get("delta") is not None]
                estado_txt = "—"
                if res and emp and regs and regs[-1].get("U"):
                    estado_txt, _, _, _ = eval_emp(
                        float(regs[-1]["delta"]), float(regs[-1]["U"]), emp)
                filas.append({
                    "Denominación":     d,
                    "EMP M1 (mg)":      emp,
                    "N cert.":          res["n"] if res else 0,
                    "Deriva (mg/año)":  round(res["slope"], 6) if res else "",
                    "u(δm_Dcr) (mg)":  round(res["u_drift"], 6) if res else "",
                    "u(m_cr) último":   round(res["u_mcr"], 6) if res and res["u_mcr"] else "",
                    "R²":               round(res["r2"], 5) if res else "",
                    "Proj. +1a (mg)":   round(res["proj_val"], 5) if res else "",
                    "Tendencia":        tendencia_label(res["slope"])[0] if res else "sin datos",
                    "Estado EMP":       estado_txt,
                })
            pd.DataFrame(filas).to_excel(writer, sheet_name="Resumen deriva", index=False)

            # Hoja 2 — Datos crudos
            filas2 = []
            for d in DENOMINATIONS:
                for reg in self.historial.get(d, []):
                    if not reg.get("fecha"): continue
                    filas2.append({
                        "Denominación": d,
                        "Fecha":        reg["fecha"],
                        "Año decimal":  round(fecha_a_año(reg["fecha"]), 5),
                        "δm_cr (mg)":   reg.get("delta", ""),
                        "U(m_cr) (mg)": reg.get("U", ""),
                        "k":            reg.get("k", ""),
                        "u(m_cr) (mg)": round(float(reg["U"]) / float(reg["k"]), 6)
                                        if reg.get("U") and reg.get("k") else "",
                        "N° certif.":   reg.get("certif", ""),
                    })
            if filas2:
                pd.DataFrame(filas2).to_excel(
                    writer, sheet_name="Datos certificados", index=False)

            # Hoja 3 — Para presupuesto incertidumbre
            filas3 = []
            for d in DENOMINATIONS:
                res = calcular_deriva(self.historial.get(d, []))
                if res:
                    filas3.append({
                        "Denominación":        d,
                        "u(m_cr) último (mg)": round(res["u_mcr"], 6) if res["u_mcr"] else "",
                        "Deriva (mg/año)":     round(res["slope"], 6),
                        "u(δm_Dcr) (mg)":     round(res["u_drift"], 6),
                        "Fuente":              "Tipo B — deriva lineal",
                        "Distribución":        "Rectangular",
                        "Divisor":             round(math.sqrt(3), 5),
                        "R²":                  round(res["r2"], 5),
                        "N":                   res["n"],
                    })
            if filas3:
                pd.DataFrame(filas3).to_excel(
                    writer, sheet_name="Para presupuesto U", index=False)

            for sn in writer.sheets:
                ws = writer.sheets[sn]
                for col in ws.columns:
                    w = max((len(str(c.value or "")) for c in col), default=0)
                    ws.column_dimensions[col[0].column_letter].width = min(w + 4, 32)

        messagebox.showinfo("Exportado", f"Reporte guardado:\n{path}")


# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure("Treeview", background=C_PANEL, fieldbackground=C_PANEL,
                foreground=C_TEXTO, rowheight=22, font=FONT_SMALL)
    s.configure("Treeview.Heading", background=C_HEADER, foreground="white",
                font=FONT_BOLD, relief="flat")
    s.map("Treeview",
          background=[("selected", C_ACCENT2)],
          foreground=[("selected", C_HEADER)])
    App(root)
    root.mainloop()
