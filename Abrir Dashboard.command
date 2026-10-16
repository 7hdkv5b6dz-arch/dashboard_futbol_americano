#!/bin/bash
# Doble clic en este archivo para abrir el dashboard en el navegador.
# (No cierres la ventana de Terminal mientras lo uses; al cerrarla, se apaga.)

cd "$(dirname "$0")" || exit 1

echo "Abriendo el Dashboard de Fútbol Americano..."
echo "(Cuando termine, se abrirá tu navegador. Para apagarlo: cierra esta ventana o pulsa Ctrl+C)"
echo ""

# Activar el entorno virtual (tiene streamlit, pandas, plotly, requests)
source .venv/bin/activate

# Streamlit abre el navegador automáticamente
streamlit run app.py
