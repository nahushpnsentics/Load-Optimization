
if [ -f venv/bin/activate ]; then
    . venv/bin/activate
else
    echo "Virtual environment not found. Creating it."
    python3 -m venv venv
    . venv/bin/activate
    pip install -r requirements.txt
fi

streamlit run app.py