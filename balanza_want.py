"""
=============================================================
  METROMECANICA - Lectura de Balanza WANT GT-30000TR
  Comunicación RS-232 | ISO/IEC 17025
  Autor: Metromecanica / Gabriel
=============================================================
  REQUISITOS:
    pip install pyserial
  
  CONFIGURACIÓN:
    Cambia COM_PORT según tu Administrador de dispositivos
=============================================================
"""

import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import csv
import os
from datetime import datetime
import threading
import time

# ─── CONFIGURACIÓN DEL PUERTO ────────────────────────────────
COM_PORT   = "COM3"       # ← CAMBIA ESTO según tu PC
BAUD_RATE  = 9600         # Probar también: 2400, 4800, 19200
BYTESIZE   = serial.EIGHTBITS
PARITY     = serial.PARITY_NONE
STOPBITS   = serial.STOPBITS_ONE
TIMEOUT    = 3            # segundos
# ─────────────────────────────────────────────────────────────


def detectar_puertos():
    """Devuelve lista de puertos COM disponibles."""
    puertos = serial.tools.list_ports.comports()
    return [p.device for p in puertos]


def parsear_lectura(raw: str):
    """
    Extrae el valor numérico y la unidad del string de la balanza.
    Formato típico WANT: '   +  0030.0 g  ' o 'ST,GS,+0030.0g'
    Retorna (valor_float, unidad_str) o (None, None) si no se puede parsear.
    """
    import re
    raw = raw.strip()
    if not raw:
        return None, None

    # Buscar número con signo y unidad (g, kg, oz, lb, ct)
    patron = r'([+-]?\s*\d+\.?\d*)\s*(g|kg|oz|lb|ct)'
    match = re.search(patron, raw, re.IGNORECASE)
    if match:
        valor_str = match.group(1).replace(" ", "")
        unidad    = match.group(2).lower()
        try:
            return float(valor_str), unidad
        except ValueError:
            return None, None
    return None, None


class AplicacionBalanza:
    def __init__(self, root):
        self.root = root
        self.root.title("Metromecanica — Lectura Balanza WANT RS-232")
        self.root.geometry("700x580")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e2e")

        self.serial_conn  = None
        self.leyendo      = False
        self.lecturas     = []          # lista de dicts para CSV
        self.archivo_csv  = None
        self.hilo_lectura = None

        self._construir_ui()
        self._actualizar_puertos()

    # ── UI ────────────────────────────────────────────────────
    def _construir_ui(self):
        COLOR_BG   = "#1e1e2e"
        COLOR_CARD = "#2a2a3e"
        COLOR_ACC  = "#7c3aed"
        COLOR_TXT  = "#e2e8f0"
        COLOR_OK   = "#22c55e"
        COLOR_ERR  = "#ef4444"

        # Título
        tk.Label(self.root, text="🔬 METROMECANICA",
                 bg=COLOR_BG, fg=COLOR_ACC,
                 font=("Segoe UI", 14, "bold")).pack(pady=(16, 0))
        tk.Label(self.root, text="Balanza WANT GT-30000TR — RS-232",
                 bg=COLOR_BG, fg="#94a3b8",
                 font=("Segoe UI", 9)).pack(pady=(0, 12))

        # ── Panel conexión ────────────────────────────────────
        frame_con = tk.LabelFrame(self.root, text=" Conexión ",
                                  bg=COLOR_CARD, fg=COLOR_TXT,
                                  font=("Segoe UI", 9, "bold"),
                                  bd=1, relief="groove")
        frame_con.pack(fill="x", padx=20, pady=(0, 8))

        row1 = tk.Frame(frame_con, bg=COLOR_CARD)
        row1.pack(fill="x", padx=12, pady=8)

        tk.Label(row1, text="Puerto COM:", bg=COLOR_CARD,
                 fg=COLOR_TXT, font=("Segoe UI", 9)).pack(side="left")
        self.combo_puerto = ttk.Combobox(row1, width=10, state="readonly")
        self.combo_puerto.pack(side="left", padx=8)

        tk.Label(row1, text="Baudrate:", bg=COLOR_CARD,
                 fg=COLOR_TXT, font=("Segoe UI", 9)).pack(side="left")
        self.combo_baud = ttk.Combobox(row1, width=8, state="readonly",
                                       values=["2400","4800","9600","19200","38400"])
        self.combo_baud.set("9600")
        self.combo_baud.pack(side="left", padx=8)

        self.btn_conectar = tk.Button(row1, text="Conectar",
                                      bg=COLOR_ACC, fg="white",
                                      font=("Segoe UI", 9, "bold"),
                                      relief="flat", padx=12,
                                      command=self._toggle_conexion)
        self.btn_conectar.pack(side="left", padx=8)

        tk.Button(row1, text="↺", bg=COLOR_CARD, fg=COLOR_TXT,
                  font=("Segoe UI", 10), relief="flat",
                  command=self._actualizar_puertos).pack(side="left")

        self.lbl_estado = tk.Label(frame_con, text="⚫ Desconectado",
                                   bg=COLOR_CARD, fg=COLOR_ERR,
                                   font=("Segoe UI", 9))
        self.lbl_estado.pack(pady=(0, 8))

        # ── Display principal ─────────────────────────────────
        frame_disp = tk.Frame(self.root, bg=COLOR_CARD,
                              bd=1, relief="groove")
        frame_disp.pack(fill="x", padx=20, pady=(0, 8))

        self.lbl_valor = tk.Label(frame_disp, text="---.-- g",
                                  bg=COLOR_CARD, fg=COLOR_OK,
                                  font=("Consolas", 42, "bold"))
        self.lbl_valor.pack(pady=(16, 4))

        self.lbl_raw = tk.Label(frame_disp, text="raw: —",
                                bg=COLOR_CARD, fg="#64748b",
                                font=("Consolas", 9))
        self.lbl_raw.pack(pady=(0, 12))

        # ── Panel calibración ─────────────────────────────────
        frame_cal = tk.LabelFrame(self.root, text=" Registro de Calibración ",
                                  bg=COLOR_CARD, fg=COLOR_TXT,
                                  font=("Segoe UI", 9, "bold"),
                                  bd=1, relief="groove")
        frame_cal.pack(fill="x", padx=20, pady=(0, 8))

        row2 = tk.Frame(frame_cal, bg=COLOR_CARD)
        row2.pack(fill="x", padx=12, pady=8)

        tk.Label(row2, text="Patrón (g):", bg=COLOR_CARD,
                 fg=COLOR_TXT, font=("Segoe UI", 9)).pack(side="left")
        self.entry_patron = tk.Entry(row2, width=10,
                                     font=("Consolas", 10))
        self.entry_patron.pack(side="left", padx=8)

        tk.Label(row2, text="Descripción:", bg=COLOR_CARD,
                 fg=COLOR_TXT, font=("Segoe UI", 9)).pack(side="left")
        self.entry_desc = tk.Entry(row2, width=20,
                                   font=("Consolas", 10))
        self.entry_desc.pack(side="left", padx=8)

        self.btn_capturar = tk.Button(row2, text="📥 Capturar Lectura",
                                      bg="#0f766e", fg="white",
                                      font=("Segoe UI", 9, "bold"),
                                      relief="flat", padx=10,
                                      command=self._capturar_lectura,
                                      state="disabled")
        self.btn_capturar.pack(side="left", padx=8)

        # ── Tabla de lecturas ─────────────────────────────────
        frame_tabla = tk.Frame(self.root, bg=COLOR_BG)
        frame_tabla.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        cols = ("N°", "Timestamp", "Patrón (g)", "Lectura (g)",
                "Error (g)", "Descripción")
        self.tabla = ttk.Treeview(frame_tabla, columns=cols,
                                  show="headings", height=6)
        anchos = [35, 140, 85, 85, 75, 150]
        for col, ancho in zip(cols, anchos):
            self.tabla.heading(col, text=col)
            self.tabla.column(col, width=ancho, anchor="center")

        scroll = ttk.Scrollbar(frame_tabla, orient="vertical",
                               command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # ── Botones inferiores ────────────────────────────────
        frame_bot = tk.Frame(self.root, bg=COLOR_BG)
        frame_bot.pack(fill="x", padx=20, pady=(0, 14))

        tk.Button(frame_bot, text="💾 Exportar CSV",
                  bg="#1d4ed8", fg="white",
                  font=("Segoe UI", 9, "bold"),
                  relief="flat", padx=12,
                  command=self._exportar_csv).pack(side="left", padx=(0, 8))

        tk.Button(frame_bot, text="🗑 Limpiar tabla",
                  bg="#374151", fg=COLOR_TXT,
                  font=("Segoe UI", 9),
                  relief="flat", padx=12,
                  command=self._limpiar_tabla).pack(side="left")

        self.lbl_contador = tk.Label(frame_bot,
                                     text="Lecturas: 0",
                                     bg=COLOR_BG, fg="#64748b",
                                     font=("Segoe UI", 9))
        self.lbl_contador.pack(side="right")

    # ── Lógica de conexión ────────────────────────────────────
    def _actualizar_puertos(self):
        puertos = detectar_puertos()
        self.combo_puerto["values"] = puertos
        if puertos:
            self.combo_puerto.set(puertos[0])

    def _toggle_conexion(self):
        if self.serial_conn and self.serial_conn.is_open:
            self._desconectar()
        else:
            self._conectar()

    def _conectar(self):
        puerto  = self.combo_puerto.get()
        baud    = int(self.combo_baud.get())
        if not puerto:
            messagebox.showwarning("Puerto", "Selecciona un puerto COM.")
            return
        try:
            self.serial_conn = serial.Serial(
                port=puerto, baudrate=baud,
                bytesize=BYTESIZE, parity=PARITY,
                stopbits=STOPBITS, timeout=TIMEOUT
            )
            self.leyendo = True
            self.hilo_lectura = threading.Thread(
                target=self._loop_lectura, daemon=True)
            self.hilo_lectura.start()

            self.lbl_estado.config(
                text=f"🟢 Conectado en {puerto} @ {baud} bps",
                fg="#22c55e")
            self.btn_conectar.config(text="Desconectar", bg="#dc2626")
            self.btn_capturar.config(state="normal")
        except serial.SerialException as e:
            messagebox.showerror("Error de conexión", str(e))

    def _desconectar(self):
        self.leyendo = False
        if self.serial_conn:
            self.serial_conn.close()
        self.lbl_estado.config(text="⚫ Desconectado", fg="#ef4444")
        self.btn_conectar.config(text="Conectar", bg="#7c3aed")
        self.btn_capturar.config(state="disabled")
        self.lbl_valor.config(text="---.-- g")
        self.lbl_raw.config(text="raw: —")

    # ── Loop de lectura en hilo separado ──────────────────────
    def _loop_lectura(self):
        while self.leyendo:
            try:
                if self.serial_conn and self.serial_conn.in_waiting > 0:
                    linea = self.serial_conn.readline()
                    raw   = linea.decode("ascii", errors="ignore").strip()
                    if raw:
                        valor, unidad = parsear_lectura(raw)
                        self.root.after(0, self._actualizar_display,
                                        raw, valor, unidad)
                time.sleep(0.1)
            except Exception:
                break

    def _actualizar_display(self, raw, valor, unidad):
        self.lbl_raw.config(text=f"raw: {raw}")
        if valor is not None:
            self.lbl_valor.config(
                text=f"{valor:>10.2f} {unidad}")
        else:
            self.lbl_valor.config(text="??? —")

    # ── Captura de lectura ────────────────────────────────────
    def _capturar_lectura(self):
        raw_actual = self.lbl_raw.cget("text").replace("raw: ", "")
        valor, unidad = parsear_lectura(raw_actual)

        if valor is None:
            messagebox.showwarning("Sin lectura",
                                   "No hay lectura válida en pantalla.")
            return

        patron_str = self.entry_patron.get().strip()
        desc       = self.entry_desc.get().strip() or "—"
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        n          = len(self.lecturas) + 1

        try:
            patron_val = float(patron_str) if patron_str else None
            error      = round(valor - patron_val, 4) if patron_val else None
        except ValueError:
            patron_val = None
            error      = None

        registro = {
            "n":          n,
            "timestamp":  timestamp,
            "patron_g":   patron_val if patron_val else "",
            "lectura_g":  valor,
            "error_g":    error if error is not None else "",
            "descripcion": desc
        }
        self.lecturas.append(registro)

        self.tabla.insert("", "end", values=(
            n, timestamp,
            f"{patron_val:.4f}" if patron_val else "—",
            f"{valor:.4f}",
            f"{error:+.4f}" if error is not None else "—",
            desc
        ))
        self.lbl_contador.config(text=f"Lecturas: {n}")

    # ── Exportar CSV ──────────────────────────────────────────
    def _exportar_csv(self):
        if not self.lecturas:
            messagebox.showinfo("Sin datos", "No hay lecturas para exportar.")
            return

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_default = f"calibracion_WANT_{fecha}.csv"
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=nombre_default
        )
        if not ruta:
            return

        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            campos = ["n", "timestamp", "patron_g",
                      "lectura_g", "error_g", "descripcion"]
            writer = csv.DictWriter(f, fieldnames=campos)
            # Encabezado de identificación
            f.write("# METROMECANICA - Registro de Calibración\n")
            f.write(f"# Balanza: WANT GT-30000TR\n")
            f.write(f"# Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("#\n")
            writer.writeheader()
            writer.writerows(self.lecturas)

        messagebox.showinfo("Exportado",
                            f"CSV guardado en:\n{ruta}")

    def _limpiar_tabla(self):
        if messagebox.askyesno("Limpiar", "¿Borrar todas las lecturas?"):
            self.lecturas.clear()
            for item in self.tabla.get_children():
                self.tabla.delete(item)
            self.lbl_contador.config(text="Lecturas: 0")


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = AplicacionBalanza(root)
    root.mainloop()
