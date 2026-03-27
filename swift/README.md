# SwiftConnect

SwiftConnect is a Flask-based vehicle QR and anonymous chat system.

## Local setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # macOS/Linux
   .venv\Scripts\activate    # Windows
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   python app.py
   ```

4. Open the app in your browser:

   ```text
   http://127.0.0.1:5000
   ```

## Render deployment

1. Create a new Web Service on Render.
2. Connect your GitHub repository.
3. Set the build command:

   ```bash
   pip install -r requirements.txt
   ```

4. Set the start command:

   ```bash
   python app.py
   ```

5. Render will automatically set `PORT` for the app.

## Notes

- The app auto-creates `static/qr_codes/` and `static/uploads/` on startup.
- QR links are generated using the live `request.host_url` so they work in Render.
- `Procfile` is included for Render compatibility.
