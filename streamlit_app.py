import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from fpdf import FPDF
import io
import os
import tempfile
import matplotlib.dates as mdates

# ==========================================
# 0. FUNCIÓN DE LIMPIEZA DE TEXTO
# ==========================================
def clean_text(text):
    if pd.isna(text): return "-"
    return str(text).encode('latin-1', 'replace').decode('latin-1')

# ==========================================
# 1. CLASE PARA EL REPORTE PDF
# ==========================================
class ReportePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 66, 134)
        self.cell(0, 10, 'Reporte de Eficiencia de Produccion', 0, 0, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

# ==========================================
# 2. MOTOR FOTOGRÁFICO DIARIO 
# ==========================================
@st.cache_data(show_spinner=False)
def procesar_datos_eventos_tc(df_e, df_s):
    df_e.columns = [str(c).strip() for c in df_e.columns]
    df_s.columns = [str(c).strip() for c in df_s.columns]

    def encontrar_col(df, busquedas, nombre_archivo):
        for b in busquedas:
            for c in df.columns:
                if b == c.upper(): return c
        for b in busquedas:
            for c in df.columns:
                if b in c.upper(): return c
        raise KeyError(f"No se encontro columna similar a {busquedas} en {nombre_archivo}")

    ce_maq = encontrar_col(df_e, ['MÁQUINA', 'MAQUINA', 'CELDA'], 'EVENTOS')
    ce_fec_ini = encontrar_col(df_e, ['FECHA INICIO'], 'EVENTOS')
    ce_fec_fin = encontrar_col(df_e, ['FECHA FIN'], 'EVENTOS')
    ce_tiempo = encontrar_col(df_e, ['TIEMPO (MIN)', 'TIEMPO PRODUCTIVO', 'TIEMPO'], 'EVENTOS')
    ce_evento = encontrar_col(df_e, ['NIVEL 1', 'EVENTO', 'ESTADO'], 'EVENTOS')
    ce_buenas = encontrar_col(df_e, ['BUENAS'], 'EVENTOS')
    
    ce_nobuenas = None
    for c in df_e.columns:
        if 'NO BUENA' in c.upper() or 'MALA' in c.upper() or 'RECHAZO' in c.upper() or 'SCRAP' in c.upper():
            ce_nobuenas = c
            break

    cols_cod_e = []
    for c in df_e.columns:
        if ('CÓDIGO' in c.upper() or 'CODIGO' in c.upper()) and ('PRODUCTO' in c.upper() or 'SEMIELABORADO' in c.upper()):
            cols_cod_e.append(c)
    if not cols_cod_e: cols_cod_e = [c for c in df_e.columns if 'PRODUCTO/SEMIELABORADO' in c.upper() and 'DESC' not in c.upper()]
    if not cols_cod_e: cols_cod_e = [c for c in df_e.columns if 'PRODUCTO' in c.upper() and 'DESC' not in c.upper()]

    cols_usr = [c for c in df_e.columns if 'USUARIO' in c.upper() or 'OPERARIO' in c.upper()]

    subset_dups = [ce_maq, ce_fec_ini, ce_fec_fin, ce_tiempo, ce_buenas] + cols_cod_e
    df_e = df_e.drop_duplicates(subset=subset_dups, keep='first').copy()

    df_e['Tiempo_Min'] = pd.to_numeric(df_e[ce_tiempo].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_e['Buenas_Num'] = pd.to_numeric(df_e[ce_buenas], errors='coerce').fillna(0)
    df_e['No_Buenas_Num'] = pd.to_numeric(df_e[ce_nobuenas], errors='coerce').fillna(0) if ce_nobuenas else 0
    df_e['Total_Pzas_Fila'] = df_e['Buenas_Num'] + df_e['No_Buenas_Num']
    df_e = df_e[df_e[ce_evento].astype(str).str.upper().str.contains('PRODUCCI')].copy()

    df_e['Máquina_Base'] = df_e[ce_maq].astype(str).str.strip().str.upper()
    df_e['Máquina_Consol'] = df_e['Máquina_Base'].replace(r'(?i).*15.*', 'CELDA 15', regex=True)

    # CORRECCIÓN DE FECHAS
    df_e['Fecha_Inicio_DT'] = pd.to_datetime(df_e[ce_fec_ini], errors='coerce', dayfirst=True)
    df_e['Fecha_Fin_DT'] = pd.to_datetime(df_e[ce_fec_fin], errors='coerce', dayfirst=True)
    mask_ini_nat = df_e['Fecha_Inicio_DT'].isna()
    if mask_ini_nat.any(): df_e.loc[mask_ini_nat, 'Fecha_Inicio_DT'] = pd.to_datetime(df_e.loc[mask_ini_nat, ce_fec_ini], errors='coerce')
    mask_fin_nat = df_e['Fecha_Fin_DT'].isna()
    if mask_fin_nat.any(): df_e.loc[mask_fin_nat, 'Fecha_Fin_DT'] = pd.to_datetime(df_e.loc[mask_fin_nat, ce_fec_fin], errors='coerce')
    
    df_e = df_e.dropna(subset=['Fecha_Inicio_DT']).copy()
    df_e['Fecha_Str'] = df_e['Fecha_Inicio_DT'].dt.strftime('%Y-%m-%d')
    df_e['Mid_DT'] = df_e['Fecha_Inicio_DT'] + (df_e['Fecha_Fin_DT'] - df_e['Fecha_Inicio_DT']) / 2

    n_list, prods_row_list = [], []
    for idx, row in df_e.iterrows():
        mid_time = row['Mid_DT']
        maq_consol = row['Máquina_Consol']
        activos = df_e[(df_e['Máquina_Consol'] == maq_consol) & (df_e['Fecha_Inicio_DT'] <= mid_time) & (df_e['Fecha_Fin_DT'] >= mid_time)]

        prods_globales = set()
        for _, r_activa in activos.iterrows():
            for c in cols_cod_e:
                val = str(r_activa.get(c, '')).strip().upper()
                if val and val not in ['NAN', 'NONE', '-', '0']: prods_globales.add(val)

        n_calc = max(1, len(prods_globales))
        if 'LINEA 2' in maq_consol and n_calc > 2: n_calc = 2
        if 'CELDA 15' in maq_consol and n_calc > 4: n_calc = 4

        prods_propios = set()
        for c in cols_cod_e:
            val = str(row.get(c, '')).strip().upper()
            if val and val not in ['NAN', 'NONE', '-', '0']: prods_propios.add(val)

        n_list.append(n_calc)
        prods_row_list.append(list(prods_propios))

    df_e['N'] = n_list
    df_e['Prods_List'] = prods_row_list
    df_e['Num_Prods_Row'] = df_e['Prods_List'].apply(lambda x: max(1, len(x)))

    prod_data = []
    for _, r in df_e.iterrows():
        num_in_row = r['Num_Prods_Row']
        pzas_asignadas = r['Total_Pzas_Fila'] / num_in_row
        for p in r['Prods_List']:
            prod_data.append({
                'Fecha_Str': r['Fecha_Str'], 'Máquina_Consol': r['Máquina_Consol'], 'Producto': p,
                'N': r['N'], 'Tiempo_Min': r['Tiempo_Min'], 'Pzas_Prod': pzas_asignadas,
                'Usuarios': [str(r.get(c, '')).strip() for c in cols_usr if pd.notna(r.get(c))]
            })

    df_prod_master = pd.DataFrame(prod_data)
    if df_prod_master.empty: raise ValueError("No se encontraron productos válidos en el archivo.")

    df_daily_prod = df_prod_master.groupby(['Fecha_Str', 'Máquina_Consol', 'Producto', 'N']).agg({
        'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
    }).reset_index()
    df_daily_prod = df_daily_prod[(df_daily_prod['Pzas_Prod'] > 0) & (df_daily_prod['Tiempo_Min'] >= 5)].copy()

    df_productos_res = df_daily_prod.groupby(['Máquina_Consol', 'Producto', 'N']).agg({
        'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
    }).reset_index()
    df_productos_res.rename(columns={'N': 'Simultaneo_Con', 'Máquina_Consol': 'Máquina'}, inplace=True)
    df_productos_res['Tiempo_Hs'] = df_productos_res['Tiempo_Min'] / 60.0

    df_e['Tiempo_Maq_Global'] = df_e['Tiempo_Min'] * (df_e['Num_Prods_Row'] / df_e['N'])
    df_e['Pzas_Maq_Global'] = df_e['Total_Pzas_Fila']

    df_daily_maq = df_e.groupby(['Fecha_Str', 'Máquina_Consol', 'N']).agg({
        'Tiempo_Maq_Global': 'sum', 'Pzas_Maq_Global': 'sum'
    }).reset_index()
    df_daily_maq = df_daily_maq[(df_daily_maq['Pzas_Maq_Global'] > 0) & (df_daily_maq['Tiempo_Maq_Global'] >= 5)].copy()

    df_global_res = df_daily_maq.groupby(['Máquina_Consol', 'N']).agg({
        'Tiempo_Maq_Global': 'sum', 'Pzas_Maq_Global': 'sum'
    }).reset_index()
    df_global_res.rename(columns={'Máquina_Consol': 'Máquina', 'Tiempo_Maq_Global': 'Tiempo_Min', 'Pzas_Maq_Global': 'Pzas_Totales'}, inplace=True)
    df_global_res['Tiempo_Hs'] = df_global_res['Tiempo_Min'] / 60.0

    valid_combos = set(zip(df_daily_prod['Fecha_Str'], df_daily_prod['Máquina_Consol'], df_daily_prod['Producto'], df_daily_prod['N']))
    usr_data = []
    for _, r in df_prod_master.iterrows():
        combo = (r['Fecha_Str'], r['Máquina_Consol'], r['Producto'], r['N'])
        if combo in valid_combos:
            usuarios = [u for u in r['Usuarios'] if u and u.upper() not in ['NAN', 'NONE', '-', '0']]
            if not usuarios: usuarios = ['Sin Operario']
            num_usr = len(usuarios)
            for u in usuarios:
                usr_data.append({
                    'Máquina': r['Máquina_Consol'], 'Producto': r['Producto'], 'Operario': u,
                    'Simultaneo_Con': r['N'], 'Tiempo_Min': r['Tiempo_Min'] / num_usr, 'Pzas_Prod': r['Pzas_Prod'] / num_usr
                })

    df_operarios_res = pd.DataFrame(usr_data)
    if not df_operarios_res.empty:
        df_operarios_res = df_operarios_res.groupby(['Máquina', 'Producto', 'Operario', 'Simultaneo_Con']).agg({
            'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'
        }).reset_index()
        df_operarios_res['Tiempo_Hs'] = df_operarios_res['Tiempo_Min'] / 60.0

    col_tc = next((c for c in df_s.columns if 'TIEMPO CICLO' in c.upper() or 'CICLO' in c.upper() or 'TC' in c.upper()), df_s.columns[-1])
    col_cod = next((c for c in df_s.columns if 'CÓDIGO PRODUCTO' in c.upper() or 'CODIGO PRODUCTO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper() and 'CÓDIGO' in c.upper()), None)
    if not col_cod: col_cod = next((c for c in df_s.columns if 'PRODUCTO' in c.upper()), df_s.columns[4])

    df_s[col_tc] = pd.to_numeric(df_s[col_tc].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
    df_s_min = df_s[[col_cod, col_tc]].drop_duplicates(subset=[col_cod], keep='first')
    df_s_min[col_cod] = df_s_min[col_cod].astype(str).str.strip().str.upper()

    df_productos_res = df_productos_res.merge(df_s_min, left_on='Producto', right_on=col_cod, how='left')
    df_productos_res.rename(columns={col_tc: 'TC'}, inplace=True)
    df_productos_res['TC'] = df_productos_res['TC'].fillna(0.0)

    df_daily_prod = df_daily_prod.merge(df_s_min, left_on='Producto', right_on=col_cod, how='left')
    df_daily_prod.rename(columns={col_tc: 'TC', 'Máquina_Consol': 'Máquina'}, inplace=True)
    df_daily_prod['TC'] = df_daily_prod['TC'].fillna(0.0)

    if not df_daily_prod.empty:
        fechas_ordenadas = pd.to_datetime(df_daily_prod['Fecha_Str']).sort_values()
        fecha_min = fechas_ordenadas.iloc[0].strftime('%d/%m/%Y')
        fecha_max = fechas_ordenadas.iloc[-1].strftime('%d/%m/%Y')
        intervalo_str = f"Periodo: {fecha_min} al {fecha_max}" if fecha_min != fecha_max else f"Periodo: {fecha_min}"
    else:
        intervalo_str = "Periodo: Sin datos"

    return df_global_res, df_productos_res, df_operarios_res, df_daily_prod, intervalo_str

# ==========================================
# 3. Y 4. REPORTES PDF (FUNCIONES ORIGINALES)
# ==========================================
def generar_pdf_produccion(maquinas, df_global, df_productos, df_operarios, incluir_operarios, intervalo_str):
    pdf = ReportePDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    if df_global.empty: return None

    for maq in maquinas:
        df_maq_global = df_global[df_global['Máquina'] == maq].copy()
        if df_maq_global.empty: continue

        pdf.add_page()
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 8, f"MÁQUINA: {maq}", ln=True)

        pdf.set_font("Arial", 'I', 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 6, intervalo_str, ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)

        if incluir_operarios:
            pdf.set_font("Arial", 'I', 8)
            pdf.multi_cell(0, 4, "NOTA: Tiempos y piezas se han repartido equitativamente entre los operarios que figuran en cada evento.")
            pdf.ln(5)

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, f"Distribución de Tiempo (Hs) - {maq}", ln=True)

        fig, ax = plt.subplots(figsize=(6, 4))
        labels = [f"Simultáneo: {int(n)}" for n in df_maq_global['N']]
        sizes = df_maq_global['Tiempo_Hs']
        colores = ['#4A90E2', '#A3D9A5', '#339933', '#A9D0F5', '#E6A8D7']

        ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colores)
        ax.axis('equal')

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            fig.savefig(tmp.name, bbox_inches='tight')
            chart = tmp.name
        plt.close(fig)

        pdf.image(chart, x=50, w=110)
        os.remove(chart)
        pdf.ln(5)

        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, "Resumen Global por Simultaneidad", ln=True)

        pdf.set_font("Arial", 'B', 8)
        pdf.set_fill_color(220, 220, 220)
        pdf.cell(40, 8, "Maquina", 1, 0, 'C', True)
        pdf.cell(35, 8, "Piezas Simultaneas", 1, 0, 'C', True)
        pdf.cell(35, 8, "Tiempo Maq. (Hs)", 1, 0, 'C', True)
        pdf.cell(40, 8, "Total Pzas Fabricadas", 1, 0, 'C', True)
        pdf.cell(40, 8, "Pzas / Hora Promedio", 1, 1, 'C', True)

        pdf.set_font("Arial", '', 8)
        for _, r in df_maq_global.sort_values('N').iterrows():
            ph_prom = r['Pzas_Totales'] / r['Tiempo_Hs'] if r['Tiempo_Hs'] > 0 else 0
            pdf.cell(40, 6, clean_text(r['Máquina'])[:20], 1, 0, 'C')
            pdf.cell(35, 6, str(int(r['N'])), 1, 0, 'C')
            pdf.cell(35, 6, f"{r['Tiempo_Hs']:.2f}", 1, 0, 'C')
            pdf.cell(40, 6, str(int(r['Pzas_Totales'])), 1, 0, 'C')
            pdf.cell(40, 6, f"{ph_prom:.2f}", 1, 1, 'C')
        pdf.ln(10)

        titulo_detalle = "Detalle de Cadencia por Producto y Operario" if incluir_operarios else "Detalle de Cadencia por Producto"
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(0, 8, titulo_detalle, ln=True)

        df_maq_prods = df_productos[df_productos['Máquina'] == maq]
        if not df_maq_prods.empty:
            productos_unicos = sorted(df_maq_prods['Producto'].unique())
            for prod in productos_unicos:
                df_p_data = df_maq_prods[df_maq_prods['Producto'] == prod].sort_values('Simultaneo_Con')

                pdf.ln(3)
                pdf.set_font("Arial", 'B', 8)
                pdf.set_fill_color(220, 220, 220)
                pdf.cell(0, 7, f"CODIGO: {prod}", 0, 1, 'L', True)

                pdf.set_font("Arial", 'B', 7)
                pdf.set_fill_color(0, 66, 134); pdf.set_text_color(255, 255, 255)
                cols_p = [("Simultaneo Con", 25), ("Tiempo Prod", 25), ("Pzas Fabricadas", 30), ("P/H Real", 25), ("Tiempo Ciclo", 25), ("P/H Estimada", 30), ("Diferencia", 30)]
                for txt, w in cols_p: pdf.cell(w, 7, txt, 1, 0, 'C', True)
                pdf.ln()

                pdf.set_font("Arial", "", 7); pdf.set_text_color(0, 0, 0)
                for _, r in df_p_data.iterrows():
                    ph_real = r['Pzas_Prod'] / r['Tiempo_Hs'] if r['Tiempo_Hs'] > 0 else 0
                    ph_est = 60 / r['TC'] if r.get('TC', 0) > 0 else 0
                    diff = ph_real - ph_est

                    pdf.cell(25, 6, str(int(r['Simultaneo_Con'])), 1, 0, 'C')
                    pdf.cell(25, 6, f"{r['Tiempo_Hs']:.2f}", 1, 0, 'C')
                    pdf.cell(30, 6, str(int(r['Pzas_Prod'])), 1, 0, 'C')
                    pdf.cell(25, 6, f"{ph_real:.2f}", 1, 0, 'C')
                    pdf.cell(25, 6, f"{r.get('TC', 0):.2f}", 1, 0, 'C')
                    pdf.cell(30, 6, f"{ph_est:.2f}", 1, 0, 'C')

                    if diff < 0: pdf.set_text_color(200, 0, 0)
                    else: pdf.set_text_color(0, 150, 0)
                    pdf.cell(30, 6, f"{diff:.2f}", 1, 1, 'C')
                    pdf.set_text_color(0, 0, 0)

                if incluir_operarios and not df_operarios.empty:
                    df_op = df_operarios[(df_operarios['Máquina'] == maq) & (df_operarios['Producto'] == prod)]
                    if not df_op.empty:
                        df_op = df_op.sort_values(by=['Simultaneo_Con', 'Operario'], ascending=[False, True])

                        pdf.ln(1)
                        pdf.set_font("Arial", 'B', 7)
                        pdf.set_fill_color(230, 230, 230)
                        cols_op = [("Operario", 65), ("Simultaneo Con", 30), ("Tiempo Prod", 30), ("Pzas Fabricadas", 35), ("P/H Real", 30)]
                        for txt, w in cols_op: pdf.cell(w, 6, txt, 1, 0, 'C', True)
                        pdf.ln()

                        pdf.set_font("Arial", "", 7)
                        for _, r in df_op.iterrows():
                            ph_op = r['Pzas_Prod'] / r['Tiempo_Hs'] if r['Tiempo_Hs'] > 0 else 0
                            pdf.cell(65, 6, clean_text(r['Operario'])[:35], 1, 0, 'L')
                            pdf.cell(30, 6, str(int(r['Simultaneo_Con'])), 1, 0, 'C')
                            pdf.cell(30, 6, f"{r['Tiempo_Hs']:.2f}", 1, 0, 'C')
                            pdf.cell(35, 6, str(int(r['Pzas_Prod'])), 1, 0, 'C')
                            pdf.cell(30, 6, f"{ph_op:.2f}", 1, 1, 'C')

    nombre = "Reporte_General_Eficiencia.pdf"
    pdf.output(nombre)
    return nombre

def generar_pagina_evolutivo(pdf, df_daily_prod, maquina_seleccionada, intervalo_str):
    df_daily = df_daily_prod[df_daily_prod['Máquina'].str.upper() == maquina_seleccionada.upper()].copy()
    if df_daily.empty: return False

    df_daily = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'}).reset_index()
    df_daily['Fecha_DT'] = pd.to_datetime(df_daily['Fecha_Str'])
    df_daily = df_daily.sort_values(by=['Fecha_DT', 'Producto'])

    df_daily['Tiempo_Hs'] = df_daily['Tiempo_Min'] / 60.0
    df_daily['PH_Real'] = np.where(df_daily['Tiempo_Hs'] > 0, df_daily['Pzas_Prod'] / df_daily['Tiempo_Hs'], 0)
    df_daily['PH_Est'] = np.where(df_daily['TC'] > 0, 60 / df_daily['TC'], 0)
    df_daily['PMin_Real'] = df_daily['PH_Real'] / 60.0
    df_daily['PMin_Est'] = df_daily['PH_Est'] / 60.0
    df_daily['Perfo'] = np.where(df_daily['PH_Est'] > 0, (df_daily['PH_Real'] / df_daily['PH_Est']) * 100, 0)

    pdf.add_page()
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, f"HISTORICO DE PRODUCCION DIARIO: {maquina_seleccionada}", ln=True, align='C')

    pdf.set_font("Arial", 'I', 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, intervalo_str, ln=True, align='C')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    fig, ax = plt.subplots(figsize=(10, 4))
    for prod in df_daily['Producto'].unique():
        df_prod = df_daily[df_daily['Producto'] == prod]
        ax.plot(df_prod['Fecha_DT'], df_prod['PH_Real'], marker='o', label=str(prod)[:20])

    ax.set_title("Evolucion de Cadencia por Codigo de Producto", fontweight='bold', fontsize=10)
    ax.set_xlabel("Fechas de Produccion")
    ax.set_ylabel("Piezas / Hora (Real)")

    # Formateo estricto de las fechas en el PDF (Día/Mes/Año)
    fechas_unicas = sorted(df_daily['Fecha_DT'].unique())
    ax.set_xticks(fechas_unicas)
    ax.set_xticklabels([pd.to_datetime(x).strftime('%d/%m/%Y') for x in fechas_unicas], rotation=45, ha='right', fontsize=7)
    
    ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=7, title="Codigos")
    ax.grid(True, linestyle=':', alpha=0.6)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
        fig.savefig(tmp.name, bbox_inches='tight')
        chart = tmp.name
    plt.close(fig)

    pdf.image(chart, x=10, w=190)
    os.remove(chart)
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 7)
    pdf.set_fill_color(0, 66, 134); pdf.set_text_color(255, 255, 255)

    cols = [("Fecha", 20), ("Codigo Producto", 50), ("Hs", 12), ("Pz Tot", 14), ("P/H R", 16), ("P/H E", 16), ("P/M R", 16), ("P/M E", 16), ("Dif", 14), ("Perfo%", 16)]
    for txt, w in cols: pdf.cell(w, 8, txt, 1, 0, 'C', True)
    pdf.ln()

    pdf.set_font("Arial", "", 7); pdf.set_text_color(0, 0, 0)

    for _, r in df_daily.iterrows():
        pdf.cell(20, 6, pd.to_datetime(r['Fecha_Str']).strftime('%d/%m/%Y'), 1, 0, 'C')
        pdf.cell(50, 6, clean_text(r['Producto'])[:35], 1, 0, 'L')
        pdf.cell(12, 6, f"{r['Tiempo_Hs']:.1f}", 1, 0, 'C')
        pdf.cell(14, 6, str(int(r['Pzas_Prod'])), 1, 0, 'C')
        pdf.cell(16, 6, f"{r['PH_Real']:.1f}", 1, 0, 'C')
        pdf.cell(16, 6, f"{r['PH_Est']:.1f}", 1, 0, 'C')
        pdf.cell(16, 6, f"{r['PMin_Real']:.2f}", 1, 0, 'C')
        pdf.cell(16, 6, f"{r['PMin_Est']:.2f}", 1, 0, 'C')

        diff = r['PH_Real'] - r['PH_Est']
        if diff < 0: pdf.set_text_color(200, 0, 0)
        else: pdf.set_text_color(0, 150, 0)
        pdf.cell(14, 6, f"{diff:.1f}", 1, 0, 'C')

        pdf.set_text_color(0, 0, 0)
        pdf.cell(16, 6, f"{r['Perfo']:.1f}%", 1, 1, 'C')

    return True

def generar_evolutivo_master(df_daily_prod, maquinas, modo, intervalo_str):
    archivos_generados = []
    if modo == '1':
        for maq in maquinas:
            pdf = ReportePDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            if generar_pagina_evolutivo(pdf, df_daily_prod, maq, intervalo_str):
                nombre = f"Reporte_Evolutivo_{maq.replace(' ','_')}.pdf"
                pdf.output(nombre)
                archivos_generados.append(nombre)
    elif modo == '2':
        pdf = ReportePDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        paginas_agregadas = False
        for maq in maquinas:
            if generar_pagina_evolutivo(pdf, df_daily_prod, maq, intervalo_str):
                paginas_agregadas = True
        if paginas_agregadas:
            nombre = "Reporte_Evolutivo_Consolidado.pdf"
            pdf.output(nombre)
            archivos_generados.append(nombre)

    return archivos_generados

# ==========================================
# 5. STREAMLIT APP UI
# ==========================================
st.set_page_config(page_title="Análisis de Cadencias", layout="wide", page_icon="⚙️")

with st.sidebar:
    st.title("⚙️ Configuración")
    st.header("1. Carga de Archivos")
    uploaded_e = st.file_uploader("📂 Archivo EVENTOS", type=['csv', 'xlsx'])
    uploaded_s = st.file_uploader("📂 Archivo TIEMPOS (Ciclo)", type=['csv', 'xlsx'])

st.title("⚙️ Análisis de Cadencias y Eficiencia")

if not (uploaded_e and uploaded_s):
    st.info("👈 Por favor, carga los archivos de Excel/CSV en el panel lateral para visualizar las cadencias.")
else:
    try:
        with st.spinner('Procesando datos, unificando fechas y cruzando tiempos de ciclo...'):
            df_e_raw = pd.read_csv(uploaded_e) if uploaded_e.name.endswith('.csv') else pd.read_excel(uploaded_e)
            df_s_raw = pd.read_csv(uploaded_s) if uploaded_s.name.endswith('.csv') else pd.read_excel(uploaded_s)
            
            df_global, df_productos, df_operarios, df_daily_prod, intervalo_str = procesar_datos_eventos_tc(df_e_raw, df_s_raw)

        maquinas_disp = sorted(df_daily_prod['Máquina'].unique())
        
        tab1, tab2 = st.tabs(["📊 Vista Detallada de Máquina", "📄 Exportación PDF"])

        # --- PESTAÑA 1: VISUALIZACIÓN WEB ---
        with tab1:
            st.markdown(f"**{intervalo_str}**")
            maq_sel = st.selectbox("📌 Seleccione la Máquina a evaluar:", maquinas_disp)
            st.divider()
            
            st.markdown(f"<h2 style='text-align: center; color: #004286;'>MÁQUINA: {maq_sel}</h2>", unsafe_allow_html=True)
            
            st.markdown("#### 1. Distribución de Tiempo Total (Hs)")
            df_maq_global = df_global[df_global['Máquina'] == maq_sel].copy()
            if not df_maq_global.empty:
                fig_pie, ax_pie = plt.subplots(figsize=(6, 3))
                labels = [f"Simultáneo: {int(n)}" for n in df_maq_global['N']]
                sizes = df_maq_global['Tiempo_Hs']
                colores = ['#4A90E2', '#A3D9A5', '#339933', '#A9D0F5', '#E6A8D7']
                ax_pie.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colores)
                ax_pie.axis('equal')
                st.pyplot(fig_pie)
            
            st.markdown("#### 2. Resumen General por Producto")
            df_m_prod = df_productos[df_productos['Máquina'] == maq_sel].copy()
            if not df_m_prod.empty:
                df_m_prod['PH_Real'] = np.where(df_m_prod['Tiempo_Hs'] > 0, df_m_prod['Pzas_Prod'] / df_m_prod['Tiempo_Hs'], 0)
                df_m_prod['PH_Est'] = np.where(df_m_prod['TC'] > 0, 60 / df_m_prod['TC'], 0)
                df_m_prod['Eficiencia (%)'] = np.where(df_m_prod['PH_Est'] > 0, (df_m_prod['PH_Real'] / df_m_prod['PH_Est']) * 100, 0)
                
                tabla_mostrar = df_m_prod[['Producto', 'Simultaneo_Con', 'Tiempo_Hs', 'Pzas_Prod', 'TC', 'PH_Real', 'PH_Est', 'Eficiencia (%)']].copy()
                st.dataframe(
                    tabla_mostrar.style.format({
                        'Tiempo_Hs': '{:.2f}', 'Pzas_Prod': '{:,.0f}', 'TC': '{:.2f}',
                        'PH_Real': '{:.1f}', 'PH_Est': '{:.1f}', 'Eficiencia (%)': '{:.1f}%'
                    }).background_gradient(subset=['Eficiencia (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )
                
            st.markdown("#### 3. Evolutivo Diario de Cadencia (PH Real)")
            df_daily = df_daily_prod[df_daily_prod['Máquina'] == maq_sel].copy()
            if not df_daily.empty:
                df_daily_grp = df_daily.groupby(['Fecha_Str', 'Producto', 'TC']).agg({'Tiempo_Min': 'sum', 'Pzas_Prod': 'sum'}).reset_index()
                df_daily_grp['Fecha_DT'] = pd.to_datetime(df_daily_grp['Fecha_Str'])
                df_daily_grp = df_daily_grp.sort_values(by=['Fecha_DT', 'Producto'])

                df_daily_grp['Tiempo_Hs'] = df_daily_grp['Tiempo_Min'] / 60.0
                df_daily_grp['PH_Real'] = np.where(df_daily_grp['Tiempo_Hs'] > 0, df_daily_grp['Pzas_Prod'] / df_daily_grp['Tiempo_Hs'], 0)
                df_daily_grp['PH_Est'] = np.where(df_daily_grp['TC'] > 0, 60 / df_daily_grp['TC'], 0)
                
                fig_line, ax_line = plt.subplots(figsize=(10, 4))
                for prod in df_daily_grp['Producto'].unique():
                    df_p = df_daily_grp[df_daily_grp['Producto'] == prod]
                    ax_line.plot(df_p['Fecha_DT'], df_p['PH_Real'], marker='o', label=str(prod)[:25])

                ax_line.set_ylabel("Piezas / Hora (Real)")
                
                # CORRECCIÓN EN EL EJE X DE LA WEB PARA EVITAR LOS ".00" Y ".12"
                fechas_unicas_web = sorted(df_daily_grp['Fecha_DT'].unique())
                ax_line.set_xticks(fechas_unicas_web)
                ax_line.set_xticklabels([pd.to_datetime(x).strftime('%d/%m/%Y') for x in fechas_unicas_web], rotation=45, ha='right')

                ax_line.legend(loc='center left', bbox_to_anchor=(1, 0.5), fontsize=8)
                ax_line.grid(True, linestyle='--', alpha=0.6)
                st.pyplot(fig_line)
                
                st.markdown("#### 4. Detalle Diario (Día a Día)")
                df_diario_ui = df_daily_grp.copy()
                df_diario_ui['Eficiencia (%)'] = np.where(df_diario_ui['PH_Est'] > 0, (df_diario_ui['PH_Real'] / df_diario_ui['PH_Est']) * 100, 0)
                df_diario_ui['Fecha'] = df_diario_ui['Fecha_DT'].dt.strftime('%d/%m/%Y')
                tabla_diaria = df_diario_ui[['Fecha', 'Producto', 'Tiempo_Hs', 'Pzas_Prod', 'TC', 'PH_Real', 'PH_Est', 'Eficiencia (%)']].iloc[::-1]
                
                st.dataframe(
                    tabla_diaria.style.format({
                        'Tiempo_Hs': '{:.2f}', 'Pzas_Prod': '{:,.0f}', 'TC': '{:.2f}',
                        'PH_Real': '{:.1f}', 'PH_Est': '{:.1f}', 'Eficiencia (%)': '{:.1f}%'
                    }).background_gradient(subset=['Eficiencia (%)'], cmap='RdYlGn', vmin=50, vmax=100),
                    use_container_width=True, hide_index=True
                )

        # --- PESTAÑA 2: MENÚ DE EXPORTACIÓN A PDF ---
        with tab2:
            st.markdown("### 📄 Configuración de Reportes PDF")
            
            opcion_reporte = st.radio(
                "Selecciona qué reporte deseas generar:", 
                ["1. Reporte General (Torta, Producto y Operario)", 
                 "2. Reporte Evolutivo Diario (Gráfico de Líneas)", 
                 "3. Generar AMBOS"]
            )

            incluir_op = False
            if "1" in opcion_reporte or "3" in opcion_reporte:
                incluir_op = st.checkbox("Incluir detalle de OPERARIOS en el Reporte General", value=True)

            maquinas_a_procesar = []
            modo_descarga = '1'

            if "2" in opcion_reporte or "3" in opcion_reporte:
                st.markdown("#### ⚙️ Selección de Máquinas para Evolutivo")
                todas_maquinas = st.checkbox("Procesar TODAS las máquinas disponibles", value=True)
                
                if todas_maquinas:
                    maquinas_a_procesar = maquinas_disp
                else:
                    maquinas_a_procesar = st.multiselect("Elige las máquinas a exportar:", maquinas_disp, default=maquinas_disp[:1])

                if len(maquinas_a_procesar) > 1:
                    modo_radio = st.radio("Formato de Exportación Evolutivo:", ["1. PDFs Individuales por Máquina", "2. Un solo PDF Consolidado"])
                    modo_descarga = '1' if "1." in modo_radio else '2'

            st.divider()
            
            if st.button("🚀 Procesar Documentos PDF", type="primary"):
                with st.spinner("Construyendo archivos PDF..."):
                    
                    if ("1" in opcion_reporte or "3" in opcion_reporte) and not df_global.empty:
                        maqs_general = sorted(df_global['Máquina'].unique())
                        res_gen = generar_pdf_produccion(maqs_general, df_global, df_productos, df_operarios, incluir_op, intervalo_str)
                        
                        if res_gen and os.path.exists(res_gen):
                            st.success(f"✅ Reporte General Generado.")
                            with open(res_gen, "rb") as f:
                                st.download_button(
                                    label="📥 Descargar Reporte General (.pdf)", 
                                    data=f, 
                                    file_name=res_gen, 
                                    mime="application/pdf"
                                )
                    
                    if ("2" in opcion_reporte or "3" in opcion_reporte) and maquinas_a_procesar:
                        archivos_evo = generar_evolutivo_master(df_daily_prod, maquinas_a_procesar, modo_descarga, intervalo_str)
                        
                        for arch in archivos_evo:
                            if os.path.exists(arch):
                                st.success(f"✅ {arch} Generado.")
                                with open(arch, "rb") as f:
                                    st.download_button(
                                        label=f"📥 Descargar {arch}", 
                                        data=f, 
                                        file_name=arch, 
                                        mime="application/pdf", 
                                        key=arch
                                    )

    except Exception as e:
        import traceback
        st.error(f"Ocurrió un error al procesar la información: {str(e)}")
        st.code(traceback.format_exc())
