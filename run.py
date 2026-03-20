import os
from app import create_app

os.environ['FLASK_DEBUG'] = '1'
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")