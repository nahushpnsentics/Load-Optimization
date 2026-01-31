@echo off
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo Virtual environment not found. Creating it.
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)
streamlit run app.py