from . import *  
from app.irsystem.models.helpers import *
from app.irsystem.models.helpers import NumpyEncoder as NumpyEncoder
from app.irsystem.models.search import search


@socketio.on('input_change', namespace='/my-namespace')
def on_input_change(data):
    # data format: {'results': {'topics': [], 'candidates': [], 'debates': []}}
    print("hey, we got input!")
    topics = data['results']['topics']
    candidates = data['results']['candidates']
    debate_filters = data['results']['debates']

    results = search(topics, candidates, debate_filters)
    socketio.emit('output_sent', results)

