from app import app, socketio
import os

port = int(os.environ.get("PORT", 5000))

if __name__ == "__main__":
  print("Flask app running at http://0.0.0.0:" + str(port))
  socketio.run(app, host="0.0.0.0", port=port)

