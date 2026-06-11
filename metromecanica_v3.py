"""
=============================================================
  METROMECANICA — Sistema Multi-Balanza v3.0
  BIOBASE (RS-232) + RADWAG AS (WiFi TCP)
  Procedimiento ABA | ISO/IEC 17025
  Coma decimal INACAL
=============================================================
  pip install pyserial
=============================================================
"""

import serial
import serial.tools.list_ports
import socket
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv, json, os, re, threading, time
from datetime import datetime, date

DIR_APP  = os.path.dirname(os.path.abspath(__file__))
FILE_PAT = os.path.join(DIR_APP, "patrones.json")

RADWAG_IP   = "192.168.18.65"
RADWAG_PORT = 4001

# ─── PALETA ──────────────────────────────────────────────────
BG      = "#080d18"; PANEL   = "#0f1828"; PANEL2  = "#141f2e"
BORDER  = "#1a2940"; ACCENT  = "#00c8e0"; ACCENT2 = "#0077b6"
GREEN   = "#22c55e"; RED     = "#ef4444"; YELLOW  = "#f59e0b"
ORANGE  = "#f97316"; TXT     = "#cdd9e5"; TXT_DIM = "#4a6480"
TEAL    = "#0d9488"
FN_MONO = ("Courier New", 10); FN_UI = ("Georgia", 9)
FN_BIG  = ("Courier New", 26, "bold")
FN_SM   = ("Georgia", 8); FN_TITLE = ("Georgia", 11, "bold")


# ════════════════════════════════════════════════════════════
#  UTILIDADES
# ════════════════════════════════════════════════════════════
def fmt(v, d=4, signo=False):
    return format(v, f"{'+' if signo else ''}.{d}f").replace(".", ",")

def parsear_serial(raw):
    m = re.search(r'([+-]?\s*\d+\.?\d*)\s*(g|kg)', raw, re.I)
    if m:
        try:
            v = float(m.group(1).replace(" ", ""))
            return (v * 1000 if m.group(2).lower() == "kg" else v)
        except: pass
    return None

def parsear_radwag(raw):
    estable = "SU A" in raw or "SI A" in raw
    m = re.search(r'([+-]?\s*\d+\.?\d+)\s*g', raw, re.I)
    if m:
        try: return float(m.group(1).replace(" ", "")), estable
        except: pass
    return None, False

def cargar_patrones():
    if os.path.exists(FILE_PAT):
        with open(FILE_PAT, "r", encoding="utf-8") as f:
            return json.load(f)
    anio = str(date.today().replace(year=date.today().year + 1))
    return [
        {"id":"PAT-1kg",   "nominal":1000.0,  "dcr":0.0, "n_cert":"—","vencimiento":anio},
        {"id":"PAT-2kg",   "nominal":2000.0,  "dcr":0.0, "n_cert":"—","vencimiento":anio},
        {"id":"PAT-5kg",   "nominal":5000.0,  "dcr":0.0, "n_cert":"—","vencimiento":anio},
        {"id":"PAT-200mg", "nominal":0.2,     "dcr":0.0, "n_cert":"—","vencimiento":anio},
        {"id":"PAT-1g",    "nominal":1.0,     "dcr":0.0, "n_cert":"—","vencimiento":anio},
        {"id":"PAT-10g",   "nominal":10.0,    "dcr":0.0, "n_cert":"—","vencimiento":anio},
    ]

def guardar_patrones(p):
    with open(FILE_PAT, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

def estado_vigencia(venc_str):
    try:
        dias = (date.fromisoformat(venc_str) - date.today()).days
        if dias < 0:   return "VENCIDO",    RED,    dias
        if dias <= 30: return "POR VENCER", ORANGE, dias
        if dias <= 90: return "PRÓXIMO",    YELLOW, dias
        return "VIGENTE", GREEN, dias
    except: return "INVÁLIDA", RED, 0


# ════════════════════════════════════════════════════════════
#  VENTANA GESTIÓN DE PATRONES
# ════════════════════════════════════════════════════════════
class VentanaPatrones(tk.Toplevel):
    def __init__(self, parent, patrones, callback):
        super().__init__(parent)
        self.title("Gestión de Pesas Patrón")
        self.geometry("820x480")
        self.configure(bg=BG)
        self.patrones = [p.copy() for p in patrones]
        self.callback = callback
        self._build()
        self._cargar_tabla()
        self.grab_set()

    def _build(self):
        tk.Frame(self, bg=ACCENT, height=3).pack(fill="x")
        hdr = tk.Frame(self, bg=BG, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PESAS PATRÓN — TRAZABILIDAD",
                 bg=BG, fg=ACCENT, font=FN_TITLE).pack(side="left")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        cols = ("ID","Nominal (g)","δmcr (g)",
                "N° Certificado","Vencimiento","Estado")
        self.tabla = ttk.Treeview(self, columns=cols,
                                  show="headings", height=12)
        for col, w in zip(cols,[100,90,90,140,110,130]):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=w, anchor="center")
        self.tabla.pack(fill="both", expand=True, padx=12, pady=8)
        self.tabla.bind("<Double-1>", self._editar)

        btns = tk.Frame(self, bg=BG, padx=12, pady=8)
        btns.pack(fill="x")
        for txt, cmd, color in [
            ("➕ Agregar",  self._agregar,  ACCENT2),
            ("✏️ Editar",   self._editar,   "#374151"),
            ("🗑 Eliminar", self._eliminar, "#7f1d1d"),
        ]:
            tk.Button(btns, text=txt, bg=color, fg="white",
                      font=FN_UI, relief="flat", padx=10, pady=4,
                      command=cmd).pack(side="left", padx=(0,6))
        tk.Button(btns, text="✔  Guardar y cerrar",
                  bg=GREEN, fg="white",
                  font=("Georgia",9,"bold"),
                  relief="flat", padx=14, pady=4,
                  command=self._guardar).pack(side="right")

    def _cargar_tabla(self):
        for i in self.tabla.get_children(): self.tabla.delete(i)
        for p in self.patrones:
            est, color, dias = estado_vigencia(p["vencimiento"])
            tag = f"c{color[1:]}"
            self.tabla.insert("","end", tags=(tag,), values=(
                p["id"], fmt(p["nominal"]),
                fmt(p["dcr"], signo=True),
                p["n_cert"], p["vencimiento"],
                f"{est} ({dias}d)" if dias >= 0 else est))
            self.tabla.tag_configure(tag, foreground=color)

    def _form_patron(self, p=None):
        win = tk.Toplevel(self)
        win.title("Editar" if p else "Nuevo patrón")
        win.geometry("400x300")
        win.configure(bg=PANEL)
        win.grab_set()
        anio = str(date.today().replace(year=date.today().year+1))
        campos = [
            ("ID / Descripción:",         "id",          p["id"]           if p else ""),
            ("Nominal (g):",              "nominal",     str(p["nominal"]) if p else "1000"),
            ("δmcr (g):",                 "dcr",         str(p["dcr"])     if p else "0.0000"),
            ("N° Certificado:",           "n_cert",      p["n_cert"]       if p else ""),
            ("Vencimiento (YYYY-MM-DD):", "vencimiento", p["vencimiento"]  if p else anio),
        ]
        entries = {}
        for i,(lbl,key,val) in enumerate(campos):
            tk.Label(win, text=lbl, bg=PANEL, fg=TXT,
                     font=FN_UI).grid(row=i, column=0,
                                      sticky="w", padx=14, pady=7)
            e = tk.Entry(win, font=FN_MONO, bg=PANEL2, fg=TXT,
                         insertbackground=ACCENT, relief="flat",
                         bd=4, width=22)
            e.insert(0, val)
            e.grid(row=i, column=1, padx=8, pady=7)
            entries[key] = e
        result = [None]
        def ok():
            try:
                result[0] = {
                    "id":          entries["id"].get().strip(),
                    "nominal":     float(entries["nominal"].get()),
                    "dcr":         float(entries["dcr"].get()),
                    "n_cert":      entries["n_cert"].get().strip(),
                    "vencimiento": entries["vencimiento"].get().strip(),
                }
                win.destroy()
            except ValueError:
                messagebox.showerror("Error",
                    "Verifica los valores numéricos.", parent=win)
        tk.Button(win, text="Aceptar", bg=ACCENT2, fg="white",
                  font=FN_UI, relief="flat", padx=12,
                  command=ok).grid(row=len(campos), column=1,
                                   sticky="e", padx=8, pady=12)
        win.wait_window()
        return result[0]

    def _agregar(self):
        nuevo = self._form_patron()
        if nuevo:
            self.patrones.append(nuevo)
            self._cargar_tabla()

    def _editar(self, event=None):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showinfo("Selección",
                "Selecciona una pesa para editar.", parent=self)
            return
        idx = self.tabla.index(sel[0])
        ed  = self._form_patron(self.patrones[idx])
        if ed:
            self.patrones[idx] = ed
            self._cargar_tabla()

    def _eliminar(self):
        sel = self.tabla.selection()
        if not sel: return
        idx = self.tabla.index(sel[0])
        if messagebox.askyesno("Eliminar",
                f"¿Eliminar {self.patrones[idx]['id']}?",
                parent=self):
            self.patrones.pop(idx)
            self._cargar_tabla()

    def _guardar(self):
        guardar_patrones(self.patrones)
        self.callback(self.patrones)
        self.destroy()


# ════════════════════════════════════════════════════════════
#  PANEL DE BALANZA GENÉRICO
# ════════════════════════════════════════════════════════════
class PanelBalanza(tk.Frame):
    def __init__(self, parent, nombre, color, capacidad,
                 division, decimales, patrones_ref, **kw):
        super().__init__(parent, bg=PANEL, **kw)
        self.nombre    = nombre
        self.color     = color
        self.decimales = decimales
        self.patrones  = patrones_ref
        self.ultimo_val = None
        self.conectado  = False
        self.paso_aba   = 0
        self.ir1 = self.it = self.ir2 = None
        self.on_aba_completo = None

        # Barra color
        tk.Frame(self, bg=color, height=4).pack(fill="x")

        # Header
        hdr = tk.Frame(self, bg=PANEL2, padx=10, pady=5)
        hdr.pack(fill="x")
        tk.Label(hdr, text=nombre, bg=PANEL2, fg=color,
                 font=("Georgia",11,"bold")).pack(side="left")
        tk.Label(hdr, text=f"  {capacidad}  d={division}",
                 bg=PANEL2, fg=TXT_DIM,
                 font=("Georgia",8,"italic")).pack(side="left")
        self.lbl_estado = tk.Label(hdr, text="⚫ Desconectado",
                                   bg=PANEL2, fg=RED, font=FN_SM)
        self.lbl_estado.pack(side="right")

        # Display
        disp = tk.Frame(self, bg=PANEL, padx=10, pady=6)
        disp.pack(fill="x")
        self.lbl_valor = tk.Label(disp, text="--,---- g",
                                  bg=PANEL, fg=GREEN, font=FN_BIG)
        self.lbl_valor.pack()
        self.lbl_raw = tk.Label(disp, text="raw: —",
                                bg=PANEL, fg=TXT_DIM,
                                font=("Courier New",7))
        self.lbl_raw.pack()
        self.lbl_estab = tk.Label(disp, text="—",
                                  bg=PANEL, fg=TXT_DIM,
                                  font=("Courier New",7))
        self.lbl_estab.pack()

        # Panel patrón
        pat_frame = tk.Frame(self, bg=PANEL2, padx=10, pady=5)
        pat_frame.pack(fill="x")
        tk.Label(pat_frame, text="Patrón:", bg=PANEL2,
                 fg=TXT, font=FN_UI).pack(side="left")
        self.combo_pat = ttk.Combobox(pat_frame, width=20,
                                      state="readonly")
        self.combo_pat.pack(side="left", padx=6)
        self.combo_pat.bind("<<ComboboxSelected>>",
                            self._on_patron)

        # Info patrón
        info = tk.Frame(self, bg=PANEL2, padx=10, pady=3)
        info.pack(fill="x")
        self.lbl_pat_info = tk.Label(
            info, text="Nominal: —  |  δmcr: —  |  Cert.: —",
            bg=PANEL2, fg=TXT_DIM,
            font=("Courier New",7))
        self.lbl_pat_info.pack(anchor="w")
        self.lbl_pat_venc = tk.Label(
            info, text="Vence: —",
            bg=PANEL2, fg=TXT_DIM,
            font=("Courier New",7))
        self.lbl_pat_venc.pack(anchor="w")
        self.actualizar_patrones()

        # ABA
        aba = tk.Frame(self, bg=PANEL2, padx=10, pady=6)
        aba.pack(fill="x")
        tk.Frame(aba, bg=color, height=1).pack(
            fill="x", pady=(0,5))
        tk.Label(aba, text="PROCEDIMIENTO ABA",
                 bg=PANEL2, fg=color,
                 font=("Georgia",7,"bold")).pack(anchor="w")

        fml = tk.Frame(aba, bg="#0a1525", padx=6, pady=3)
        fml.pack(fill="x", pady=(3,5))
        tk.Label(fml, text="δmct = It − (Ir1+Ir2)/2 + δmcr",
                 bg="#0a1525", fg=color,
                 font=("Courier New",8,"bold")).pack()

        # Campo ID pesa
        g = tk.Frame(aba, bg=PANEL2)
        g.pack(fill="x", pady=(0,4))
        tk.Label(g, text="ID pesa:", bg=PANEL2, fg=TXT,
                 font=FN_UI, width=8,
                 anchor="w").grid(row=0, column=0,
                                  sticky="w", pady=2)
        self.e_desc = tk.Entry(g, width=18,
                               font=("Courier New",9),
                               bg=PANEL, fg=TXT,
                               insertbackground=color,
                               relief="flat", bd=2)
        self.e_desc.grid(row=0, column=1, padx=4, pady=2)

        # Indicador paso
        self.lbl_paso = tk.Label(
            aba, text="▶  Presiona 'Iniciar ABA'",
            bg=PANEL2, fg=TXT_DIM,
            font=("Courier New",7,"bold"),
            wraplength=270, justify="left")
        self.lbl_paso.pack(anchor="w", pady=(0,3))

        # Valores Ir1, It, Ir2
        vals = tk.Frame(aba, bg=PANEL2)
        vals.pack(fill="x", pady=(0,3))
        for i,(lbl,attr) in enumerate([
                ("Ir1:","lbl_ir1"),
                ("It: ","lbl_it"),
                ("Ir2:","lbl_ir2")]):
            tk.Label(vals, text=lbl, bg=PANEL2, fg=TXT_DIM,
                     font=("Courier New",9),
                     width=4).grid(row=i, column=0, sticky="w")
            lv = tk.Label(vals, text="—", bg=PANEL2, fg=TXT,
                          font=("Courier New",9),
                          width=16, anchor="e")
            lv.grid(row=i, column=1, padx=4)
            setattr(self, attr, lv)

        # Resultado ABA
        self.lbl_res = tk.Label(
            aba, text="—", bg=PANEL2, fg=GREEN,
            font=("Courier New",8,"bold"),
            wraplength=270, justify="left")
        self.lbl_res.pack(anchor="w", pady=(0,4))

        # Botones
        btns = tk.Frame(aba, bg=PANEL2)
        btns.pack(fill="x")
        self.btn_iniciar = tk.Button(
            btns, text="▶ Iniciar ABA",
            bg=color, fg="white",
            font=("Georgia",8,"bold"),
            relief="flat", padx=8, pady=2,
            command=self.iniciar_aba)
        self.btn_iniciar.pack(side="left", padx=(0,4))
        self.btn_capturar = tk.Button(
            btns, text="📥 Capturar lectura",
            bg="#166534", fg="white",
            font=("Georgia",9,"bold"),
            relief="flat", padx=12, pady=4,
            state="disabled",
            command=self.capturar)
        self.btn_capturar.pack(side="left", padx=(0,4))
        tk.Button(btns, text="✕",
                  bg=PANEL, fg=TXT_DIM,
                  font=("Georgia",8), relief="flat",
                  padx=6, pady=2,
                  command=self.cancelar_aba).pack(side="left")

    # ── Actualizar display ────────────────────────────────────
    def set_valor(self, valor, raw, estable=True):
        self.ultimo_val = valor
        self.lbl_raw.config(
            text=f"raw: {(raw or '—')[:45]}")
        if valor is not None:
            self.lbl_valor.config(
                text=f"{fmt(valor, self.decimales)} g",
                fg=GREEN)
            self.lbl_estab.config(
                text="✓ Estable" if estable else "~ Inestable",
                fg=GREEN if estable else YELLOW)
        else:
            self.lbl_valor.config(text="--,---- g", fg=TXT_DIM)
            self.lbl_estab.config(text="—", fg=TXT_DIM)

    def set_conectado(self, ok, msg=""):
        self.conectado = ok
        self.lbl_estado.config(
            text=f"🟢 {msg}" if ok else f"⚫ {msg}",
            fg=GREEN if ok else RED)
        self.btn_capturar.config(
            state="normal" if ok else "disabled")
        self.btn_iniciar.config(
            state="normal" if ok else "disabled")

    # ── Patrones ─────────────────────────────────────────────
    def actualizar_patrones(self):
        opts = [f"{p['id']}  ({int(p['nominal'])} g)"
                if p['nominal'] >= 1
                else f"{p['id']}  ({p['nominal']} g)"
                for p in self.patrones]
        self.combo_pat["values"] = opts
        if opts:
            self.combo_pat.set(opts[0])
            self._on_patron()

    def _on_patron(self, event=None):
        idx = self.combo_pat.current()
        if idx < 0 or idx >= len(self.patrones): return
        p = self.patrones[idx]
        est, color, dias = estado_vigencia(p["vencimiento"])
        self.lbl_pat_info.config(
            text=f"Nominal: {fmt(p['nominal'])} g  |  "
                 f"δmcr: {fmt(p['dcr'], signo=True)} g  |  "
                 f"Cert.: {p['n_cert']}")
        self.lbl_pat_venc.config(
            text=f"Vence: {p['vencimiento']}  [{est}]",
            fg=color)

    def patron_actual(self):
        idx = self.combo_pat.current()
        if 0 <= idx < len(self.patrones):
            return self.patrones[idx]
        return None

    # ── Captura ───────────────────────────────────────────────
    def capturar(self):
        if self.ultimo_val is None:
            messagebox.showwarning("Sin lectura",
                "No hay lectura válida.")
            return
        if self.paso_aba > 0:
            self._paso_aba(self.ultimo_val)

    # ── ABA ──────────────────────────────────────────────────
    def iniciar_aba(self):
        if not self.conectado:
            messagebox.showwarning("Conexión",
                "Conecta la balanza primero.")
            return
        pat = self.patron_actual()
        if not pat:
            messagebox.showwarning("Patrón",
                "Selecciona una pesa patrón.")
            return
        est, _, _ = estado_vigencia(pat["vencimiento"])
        if est == "VENCIDO":
            if not messagebox.askyesno("⚠ Patrón VENCIDO",
                    f"{pat['id']} está VENCIDO.\n"
                    "¿Continuar de todas formas?"):
                return
        self.paso_aba = 1
        self.ir1 = self.it = self.ir2 = None
        for a in ("lbl_ir1","lbl_it","lbl_ir2"):
            getattr(self,a).config(text="—", fg=TXT)
        self.lbl_res.config(text="—", fg=GREEN)
        self._upd_paso()

    def _upd_paso(self):
        msgs = {
            1:"📍 1/3 — PESA REFERENCIA → Capturar",
            2:"📍 2/3 — PESA A CALIBRAR → Capturar",
            3:"📍 3/3 — PESA REFERENCIA (2da) → Capturar",
        }
        self.lbl_paso.config(
            text=msgs.get(self.paso_aba,
                          "▶  Presiona 'Iniciar ABA'"),
            fg=YELLOW if self.paso_aba > 0 else TXT_DIM)

    def _paso_aba(self, val):
        d = self.decimales
        if self.paso_aba == 1:
            self.ir1 = val
            self.lbl_ir1.config(
                text=f"{fmt(val,d)} g", fg=GREEN)
            self.paso_aba = 2
        elif self.paso_aba == 2:
            self.it = val
            self.lbl_it.config(
                text=f"{fmt(val,d)} g", fg=GREEN)
            self.paso_aba = 3
        elif self.paso_aba == 3:
            self.ir2 = val
            self.lbl_ir2.config(
                text=f"{fmt(val,d)} g", fg=GREEN)
            self._calc_aba()
            return
        self._upd_paso()

    def _calc_aba(self):
        pat     = self.patron_actual()
        dcr     = pat["dcr"] if pat else 0.0
        ir_prom = (self.ir1 + self.ir2) / 2
        dct     = self.it - ir_prom + dcr
        desc    = self.e_desc.get().strip() or "—"
        d       = self.decimales
        self.lbl_res.config(
            text=f"δmct = {fmt(dct,d,True)} g\n"
                 f"Ir_prom = {fmt(ir_prom,d)} g  |  {desc}",
            fg=GREEN if abs(dct) < 0.5 else YELLOW)
        self.lbl_paso.config(
            text=f"✔  ABA completo — δmct = {fmt(dct,d,True)} g\n"
                 f"   Presiona 'Iniciar ABA' para nuevo ensayo",
            fg=GREEN)
        self.paso_aba = 0
        if self.on_aba_completo:
            self.on_aba_completo({
                "balanza":  self.nombre,
                "id_pesa":  desc,
                "patron_id":pat["id"] if pat else "—",
                "nominal":  pat["nominal"] if pat else 0,
                "n_cert":   pat["n_cert"] if pat else "—",
                "ir1":  self.ir1, "it": self.it,
                "ir2":  self.ir2, "ir_prom": ir_prom,
                "dct":  dct, "dcr": dcr,
            })

    def cancelar_aba(self):
        self.paso_aba = 0
        self.ir1 = self.it = self.ir2 = None
        for a in ("lbl_ir1","lbl_it","lbl_ir2"):
            getattr(self,a).config(text="—", fg=TXT)
        self._upd_paso()


# ════════════════════════════════════════════════════════════
#  CONEXIÓN BIOBASE (RS-232)
# ════════════════════════════════════════════════════════════
class ConexionBiobase:
    def __init__(self, panel):
        self.panel  = panel
        self.ser    = None
        self.activo = False

    def conectar(self, puerto, baud=9600):
        try:
            self.ser = serial.Serial(
                port=puerto, baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=3)
            self.activo = True
            threading.Thread(target=self._loop,
                             daemon=True).start()
            self.panel.set_conectado(
                True, f"{puerto} @ {baud}")
            return True
        except Exception as e:
            self.panel.set_conectado(False, str(e)[:30])
            return False

    def desconectar(self):
        self.activo = False
        if self.ser:
            try: self.ser.close()
            except: pass
        self.panel.set_conectado(False, "Desconectado")

    def _loop(self):
        while self.activo:
            try:
                if self.ser and self.ser.in_waiting > 0:
                    raw = self.ser.readline().decode(
                        "ascii", errors="ignore").strip()
                    if raw:
                        val = parsear_serial(raw)
                        self.panel.after(
                            0, self.panel.set_valor,
                            val, raw, True)
                        # PRINT detectado → capturar paso ABA
                        if val is not None and \
                                self.panel.paso_aba > 0:
                            self.panel.after(
                                0, self.panel._paso_aba, val)
                time.sleep(0.05)
            except: break


# ════════════════════════════════════════════════════════════
#  CONEXIÓN RADWAG (WiFi TCP) con reconexión automática
# ════════════════════════════════════════════════════════════
class ConexionRadwag:
    def __init__(self, panel):
        self.panel  = panel
        self.sock   = None
        self.activo = False
        self.ip     = RADWAG_IP
        self.port   = RADWAG_PORT

    def conectar(self, ip=None, port=None):
        if ip:   self.ip   = ip
        if port: self.port = port
        self.activo = True
        threading.Thread(target=self._loop_con_reconexion,
                         daemon=True).start()
        return True

    def desconectar(self):
        self.activo = False
        self._cerrar_socket()
        self.panel.set_conectado(False, "Desconectado")

    def _cerrar_socket(self):
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock = None

    def _conectar_socket(self):
        """Intenta conectar hasta 3 veces."""
        self._cerrar_socket()
        for intento in range(3):
            try:
                s = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET,
                             socket.SO_REUSEADDR, 1)
                s.settimeout(5)
                s.connect((self.ip, self.port))
                s.settimeout(2)
                self.sock = s
                self.panel.after(
                    0, self.panel.set_conectado,
                    True, f"WiFi {self.ip}:{self.port}")
                return True
            except Exception as e:
                self.panel.after(
                    0, self.panel.set_conectado,
                    False,
                    f"Intento {intento+1}/3...")
                time.sleep(2)
        return False

    def _loop_con_reconexion(self):
        """Loop con reconexión automática si se pierde la conexión."""
        while self.activo:
            # Intentar conectar
            if not self._conectar_socket():
                time.sleep(3)  # esperar antes de reintentar
                continue

            # Leer datos
            buffer = ""
            # Solicitar transmisión continua
            try:
                self.sock.send(b'C 1\r\n')
            except: pass
            while self.activo:
                try:
                    data = self.sock.recv(256)
                    if not data:
                        break  # conexión cerrada
                    buffer += data.decode("ascii", errors="ignore")
                    while "\r\n" in buffer:
                        linea, buffer = buffer.split("\r\n", 1)
                        linea = linea.strip()
                        if linea:
                            val, est = parsear_radwag(linea)
                            self.panel.after(
                                0, self.panel.set_valor,
                                val, linea, est)
                            # Radwag: NO captura ABA
                            # automáticamente — el metrológo
                            # presiona "Capturar" en pantalla
                except socket.timeout:
                    continue
                except Exception:
                    break  # reconectar

            if self.activo:
                self.panel.after(
                    0, self.panel.set_conectado,
                    False, "Reconectando...")
                time.sleep(2)


# ════════════════════════════════════════════════════════════
#  APLICACIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════
class App:
    def __init__(self, root):
        self.root     = root
        self.root.title(
            "METROMECANICA — Multi-Balanza v3.0 | ISO/IEC 17025")
        self.root.geometry("1220x780")
        self.root.configure(bg=BG)
        self.root.minsize(1000, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.ensayos  = []
        self.patrones = cargar_patrones()

        self._build_ui()
        self._tick()
        self._check_vigencias()

    def _on_close(self):
        """Cerrar limpiamente todas las conexiones."""
        if hasattr(self, 'cx_biobase'):
            self.cx_biobase.desconectar()
        if hasattr(self, 'cx_radwag'):
            self.cx_radwag.desconectar()
        self.root.destroy()

    def _build_ui(self):
        # Header
        tk.Frame(self.root, bg=ACCENT, height=3).pack(fill="x")
        hdr = tk.Frame(self.root, bg=BG, padx=20, pady=8)
        hdr.pack(fill="x")
        tk.Label(hdr, text="METROMECANICA",
                 bg=BG, fg=ACCENT,
                 font=("Georgia",14,"bold")).pack(side="left")
        tk.Label(hdr,
                 text="  Multi-Balanza  |  ISO/IEC 17025  |  ABA",
                 bg=BG, fg=TXT_DIM,
                 font=("Georgia",8,"italic")).pack(side="left")
        self.lbl_reloj = tk.Label(hdr, bg=BG, fg=TXT_DIM,
                                  font=("Courier New",9))
        self.lbl_reloj.pack(side="right")
        tk.Button(hdr, text="⚙ Patrones",
                  bg=PANEL2, fg=ACCENT, font=FN_UI,
                  relief="flat", padx=8, pady=2,
                  command=self._abrir_patrones).pack(
            side="right", padx=8)
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Columna BIOBASE ───────────────────────────────────
        col1 = tk.Frame(body, bg=BG)
        col1.pack(side="left", fill="both",
                  expand=True, padx=(0,4))
        self._panel_cx_biobase(col1)
        self.panel_bio = PanelBalanza(
            col1, "BIOBASE", ACCENT2,
            "5 000 g", "0,01 g", 2,
            self.patrones)
        self.panel_bio.pack(fill="both", expand=True)
        self.panel_bio.on_aba_completo = self._registrar_aba
        self.cx_biobase = ConexionBiobase(self.panel_bio)

        # ── Columna RADWAG ────────────────────────────────────
        col2 = tk.Frame(body, bg=BG)
        col2.pack(side="left", fill="both",
                  expand=True, padx=4)
        self._panel_cx_radwag(col2)
        self.panel_rad = PanelBalanza(
            col2, "RADWAG AS", TEAL,
            "220 g", "0,00001 g", 5,
            self.patrones)
        self.panel_rad.pack(fill="both", expand=True)
        self.panel_rad.on_aba_completo = self._registrar_aba
        self.cx_radwag = ConexionRadwag(self.panel_rad)

        # ── Columna Registro ──────────────────────────────────
        col3 = tk.Frame(body, bg=BG)
        col3.pack(side="right", fill="both",
                  expand=True, padx=(4,0))
        self._panel_registro(col3)

        # Footer
        foot = tk.Frame(self.root, bg=PANEL)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x")
        f2 = tk.Frame(foot, bg=PANEL, padx=12, pady=5)
        f2.pack(fill="x")
        tk.Button(f2, text="💾 Exportar CSV",
                  bg=ACCENT2, fg="white",
                  font=("Georgia",9,"bold"),
                  relief="flat", padx=12, pady=3,
                  command=self._exportar).pack(
            side="left", padx=(0,6))
        tk.Button(f2, text="🗑 Limpiar",
                  bg=PANEL2, fg=TXT, font=FN_UI,
                  relief="flat", padx=12, pady=3,
                  command=self._limpiar).pack(side="left")
        self.lbl_cont = tk.Label(
            f2, text="Ensayos: 0",
            bg=PANEL, fg=TXT_DIM, font=FN_SM)
        self.lbl_cont.pack(side="right")
        tk.Label(f2,
                 text="Coma decimal INACAL  |  δmct = It−(Ir1+Ir2)/2+δmcr",
                 bg=PANEL, fg=TXT_DIM, font=FN_SM).pack(
            side="right", padx=16)

    def _panel_cx_biobase(self, parent):
        p = tk.Frame(parent, bg=PANEL2, padx=10, pady=5)
        p.pack(fill="x", pady=(0,4))
        tk.Label(p, text="BIOBASE — RS-232",
                 bg=PANEL2, fg=ACCENT2,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(
            fill="x", pady=(2,4))
        row = tk.Frame(p, bg=PANEL2)
        row.pack(fill="x")
        tk.Label(row, text="Puerto:", bg=PANEL2,
                 fg=TXT, font=FN_UI).pack(side="left")
        self.combo_bio_port = ttk.Combobox(
            row, width=7, state="readonly")
        puertos = [x.device for x in
                   serial.tools.list_ports.comports()]
        self.combo_bio_port["values"] = puertos
        self.combo_bio_port.set(
            "COM6" if "COM6" in puertos
            else (puertos[0] if puertos else ""))
        self.combo_bio_port.pack(side="left", padx=4)
        tk.Label(row, text="Baud:", bg=PANEL2,
                 fg=TXT, font=FN_UI).pack(side="left")
        self.combo_bio_baud = ttk.Combobox(
            row, width=6, state="readonly",
            values=["2400","4800","9600","19200"])
        self.combo_bio_baud.set("9600")
        self.combo_bio_baud.pack(side="left", padx=4)
        self.btn_bio = tk.Button(
            row, text="Conectar", bg=ACCENT2, fg="white",
            font=("Georgia",8,"bold"), relief="flat",
            padx=8, pady=2, command=self._toggle_bio)
        self.btn_bio.pack(side="left", padx=4)
        tk.Button(row, text="↺", bg=PANEL2, fg=TXT_DIM,
                  font=("Georgia",10), relief="flat",
                  command=self._refresh_ports).pack(side="left")

    def _panel_cx_radwag(self, parent):
        p = tk.Frame(parent, bg=PANEL2, padx=10, pady=5)
        p.pack(fill="x", pady=(0,4))
        tk.Label(p, text="RADWAG AS — WiFi TCP",
                 bg=PANEL2, fg=TEAL,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(p, bg=BORDER, height=1).pack(
            fill="x", pady=(2,4))
        row = tk.Frame(p, bg=PANEL2)
        row.pack(fill="x")
        tk.Label(row, text="IP:", bg=PANEL2,
                 fg=TXT, font=FN_UI).pack(side="left")
        self.e_ip = tk.Entry(row, width=14,
                             font=("Courier New",9),
                             bg=PANEL, fg=TXT,
                             insertbackground=TEAL,
                             relief="flat", bd=2)
        self.e_ip.insert(0, RADWAG_IP)
        self.e_ip.pack(side="left", padx=4)
        tk.Label(row, text="Puerto:", bg=PANEL2,
                 fg=TXT, font=FN_UI).pack(side="left")
        self.e_port = tk.Entry(row, width=5,
                               font=("Courier New",9),
                               bg=PANEL, fg=TXT,
                               insertbackground=TEAL,
                               relief="flat", bd=2)
        self.e_port.insert(0, str(RADWAG_PORT))
        self.e_port.pack(side="left", padx=4)
        self.btn_rad = tk.Button(
            row, text="Conectar", bg=TEAL, fg="white",
            font=("Georgia",8,"bold"), relief="flat",
            padx=8, pady=2, command=self._toggle_rad)
        self.btn_rad.pack(side="left", padx=4)

    def _panel_registro(self, parent):
        outer = tk.Frame(parent, bg=BORDER)
        outer.pack(fill="both", expand=True)
        tk.Frame(outer, bg=ACCENT, width=3).pack(
            side="left", fill="y")
        inner = tk.Frame(outer, bg=PANEL, padx=8, pady=8)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text="REGISTRO DE ENSAYOS ABA",
                 bg=PANEL, fg=ACCENT,
                 font=("Georgia",7,"bold")).pack(anchor="w")
        tk.Frame(inner, bg=BORDER, height=1).pack(
            fill="x", pady=(2,6))

        cols = ("N°","Balanza","Timestamp","ID Pesa",
                "Patrón","Ir1","It","Ir2","Ir_prom","δmct")
        self.tabla = ttk.Treeview(inner, columns=cols,
                                  show="headings")
        for col, w in zip(cols,
                          [28,70,120,80,70,72,72,72,78,72]):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=w,
                              anchor="center", minwidth=28)
        sy = ttk.Scrollbar(inner, orient="vertical",
                           command=self.tabla.yview)
        sx = ttk.Scrollbar(inner, orient="horizontal",
                           command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sy.set,
                             xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        self.tabla.pack(fill="both", expand=True)
        sx.pack(fill="x")

        self.lbl_ult = tk.Label(
            inner, text="—", bg=PANEL, fg=GREEN,
            font=("Courier New",8,"bold"),
            wraplength=290, justify="left")
        self.lbl_ult.pack(anchor="w", pady=(5,0))

    # ── Reloj ────────────────────────────────────────────────
    def _tick(self):
        self.lbl_reloj.config(
            text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(1000, self._tick)

    # ── Conexiones ───────────────────────────────────────────
    def _refresh_ports(self):
        puertos = [x.device for x in
                   serial.tools.list_ports.comports()]
        self.combo_bio_port["values"] = puertos

    def _toggle_bio(self):
        if self.cx_biobase.activo:
            self.cx_biobase.desconectar()
            self.btn_bio.config(text="Conectar", bg=ACCENT2)
        else:
            if self.cx_biobase.conectar(
                    self.combo_bio_port.get(),
                    int(self.combo_bio_baud.get())):
                self.btn_bio.config(
                    text="Desconectar", bg=RED)

    def _toggle_rad(self):
        if self.cx_radwag.activo:
            self.cx_radwag.desconectar()
            self.btn_rad.config(text="Conectar", bg=TEAL)
        else:
            ip   = self.e_ip.get().strip()
            port = int(self.e_port.get().strip())
            self.cx_radwag.conectar(ip, port)
            self.btn_rad.config(text="Desconectar", bg=RED)

    # ── Registro ABA ─────────────────────────────────────────
    def _registrar_aba(self, datos):
        n   = len(self.ensayos) + 1
        ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bal = datos["balanza"]
        d   = 5 if "RADWAG" in bal else 2

        ensayo = {
            "n": n, "balanza": bal, "timestamp": ts,
            "id_pesa":   datos["id_pesa"],
            "patron_id": datos["patron_id"],
            "nominal_g": datos["nominal"],
            "n_cert":    datos["n_cert"],
            "ir1":  round(datos["ir1"],   d),
            "it":   round(datos["it"],    d),
            "ir2":  round(datos["ir2"],   d),
            "ir_prom": round(datos["ir_prom"], d),
            "dct":  round(datos["dct"],   d),
            "dcr":  datos["dcr"],
        }
        self.ensayos.append(ensayo)

        self.tabla.insert("","end", values=(
            n, bal, ts,
            datos["id_pesa"], datos["patron_id"],
            fmt(datos["ir1"],    d),
            fmt(datos["it"],     d),
            fmt(datos["ir2"],    d),
            fmt(datos["ir_prom"],d),
            fmt(datos["dct"],    d, True),
        ))
        self.lbl_ult.config(
            text=f"[{bal}]  {datos['id_pesa']}  "
                 f"δmct={fmt(datos['dct'],d,True)} g  "
                 f"Ir_prom={fmt(datos['ir_prom'],d)} g",
            fg=GREEN if abs(datos["dct"]) < 0.5 else YELLOW)
        self.lbl_cont.config(text=f"Ensayos: {n}")

    # ── Patrones ─────────────────────────────────────────────
    def _abrir_patrones(self):
        def cb(nuevos):
            self.patrones = nuevos
            self.panel_bio.patrones = nuevos
            self.panel_rad.patrones = nuevos
            self.panel_bio.actualizar_patrones()
            self.panel_rad.actualizar_patrones()
        VentanaPatrones(self.root, self.patrones, cb)

    def _check_vigencias(self):
        alertas = []
        for p in self.patrones:
            est, _, dias = estado_vigencia(p["vencimiento"])
            if est in ("VENCIDO","POR VENCER","PRÓXIMO"):
                alertas.append(
                    f"• {p['id']}: {est} ({abs(dias)}d)")
        if alertas:
            messagebox.showwarning(
                "Alertas de Trazabilidad",
                "VIGENCIA DE PATRONES:\n\n" +
                "\n".join(alertas))

    # ── CSV ──────────────────────────────────────────────────
    def _exportar(self):
        if not self.ensayos:
            messagebox.showinfo("Sin datos",
                "No hay ensayos para exportar.")
            return
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV","*.csv")],
            initialfile=f"calibracion_multibalanza_{fecha}.csv")
        if not ruta: return
        with open(ruta,"w",newline="",
                  encoding="utf-8-sig") as f:
            f.write("# METROMECANICA — Metrología y Calibración SAC\n")
            f.write("# Multi-Balanza: BIOBASE (RS-232) + RADWAG AS (WiFi)\n")
            f.write("# Procedimiento ABA | Norma ISO/IEC 17025\n")
            f.write(f"# Generado: "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Fórmula: δmct = It - (Ir1+Ir2)/2 + δmcr\n#\n")
            campos = ["n","balanza","timestamp","id_pesa",
                      "patron_id","nominal_g","n_cert",
                      "ir1","it","ir2","ir_prom","dct","dcr"]
            w = csv.DictWriter(f, fieldnames=campos)
            w.writeheader()
            for e in self.ensayos:
                row = e.copy()
                d = 5 if "RADWAG" in e["balanza"] else 2
                for k in ["ir1","it","ir2","ir_prom",
                          "dct","dcr"]:
                    if isinstance(row[k], float):
                        row[k] = fmt(row[k], d,
                                     k in ["dct","dcr"])
                w.writerow(row)
            # Resumen certificado
            f.write("#\n# --- RESUMEN PARA CERTIFICADO ---\n")
            f.write("# Balanza,ID Pesa,Patrón,Nominal(g),"
                    "δmct(g),δmcr(g),N°Cert\n")
            for e in self.ensayos:
                d = 5 if "RADWAG" in e["balanza"] else 2
                f.write(
                    f"# {e['balanza']},{e['id_pesa']},"
                    f"{e['patron_id']},{e['nominal_g']},"
                    f"{fmt(e['dct'],d,True)},"
                    f"{fmt(e['dcr'],d,True)},"
                    f"{e['n_cert']}\n")
        messagebox.showinfo("Exportado",
                            f"CSV guardado:\n{ruta}")

    def _limpiar(self):
        if messagebox.askyesno("Limpiar",
                "¿Borrar todos los ensayos?"):
            self.ensayos.clear()
            for i in self.tabla.get_children():
                self.tabla.delete(i)
            self.lbl_cont.config(text="Ensayos: 0")
            self.lbl_ult.config(text="—")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
