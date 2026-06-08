# Local AI D&D Engine

A fully local, multi-agent AI tabletop RPG engine. This application uses a Python/Flask backend to run a Dungeon Master and three autonomous AI player characters using the Google Gemini API.

## Requirements
* Python 3.9+
* A valid Google Gemini API Key.
* **Important:** Your API key must have access to **Gemini 2.5 Pro** and **Gemini 2.5 Flash**. The engine specifically calls these models and will fail on older versions.

1. **Clone the repository:**
   `git clone <your_github_url_here>`
   `cd dnd-engine`

**Configure your API Key:**
2.   Create a new file in the `core` folder named exactly `.env`. Inside that file, add your API key like this:
   `GEMINI_API_KEY=your_actual_api_key_here`
   
3. **Create and activate a virtual environment:**
   `python3 -m venv venv`
   `source venv/bin/activate` *(Note: On Windows, use `venv\Scripts\activate`)*

4. **Install dependencies:**
   `pip install -r requirements.txt`
   
5. **Start the Engine:**
   Run the server from the main directory:
   `python3 core/engine.py`

6. **Play:**
   Open your browser and navigate to `http://localhost:2627`
