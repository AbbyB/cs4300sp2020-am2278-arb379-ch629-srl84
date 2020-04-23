from app.irsystem.models.videos import get_video
from . import *


# test topics
# 'healthcare', 'terrorism', 'national security', 'gun policy', 'taxes',
# 'education', 'economy', 'immigration', 'abortion', 'federal deficit',
# 'climate change', 'environment', 'war', 'corona virus', 'covid 19'


# if i is in result, return the exchange
# otherwise, create a new one
def get_exchange(i, transcript, added, result):
    if i in result:
        return result[i]
    elif i in added:
        # must be a response
        return get_exchange(transcript[i]['response'], transcript, added, result)
    else:
        added.add(i)
        result[i] = [transcript[i]]
        return result[i]


def exact_search(transcript, topic, candidates):
    topic = topic.lower()
    added = set()
    result = dict()
    for i, quote in enumerate(transcript):
        if i not in added and topic in quote['text'].lower() and (quote['speaker'].lower() in candidates or len(candidates) == 0):
            # if in questions, then add question and all responses
            if quote['question'] and quote['response']:
                exchange = [quote]
                added.add(i)
                for q in quote['response']:
                    exchange.append(transcript[q])
                    added.add(q)
                result[i] = exchange
            # otherwise only add question (if not already) and response
            elif not quote['question'] and type(quote['response']) == int:
                added.add(i)
                first_i = quote['response']
                z = get_exchange(first_i, transcript, added, result)
                exchange = z
                exchange.append(quote)
    return result.values()


def search(topics, candidates, debate_filters):
    candidates = [candidate.lower() for candidate in candidates]

    # TODO: add in candidate filtering
    # filter debates by title, tags, date, and description
    # right now filter by debate
    debates = dict()
    if debate_filters:
        for debate_filter in debate_filters:
            for debate in db.debates.find({'title': debate_filter}):
                debates[debate['url']] = debate
            for debate in db.debates.find({'tags': debate_filter}):
                debates[debate['url']] = debate
            for debate in db.debates.find({'date': debate_filter}):
                debates[debate['url']] = debate
            for debate in db.debates.find({'description': debate_filter}):
                debates[debate['url']] = debate

        debates = [v for v in debates.values() if 'debate' in v['tags']]
    else:
        debates = db.debates.find({'tags': 'debate'})

    results = []
    for debate in debates:
        relevant = []
        for topic in topics:
            for part in debate['parts']:
                for x in exact_search(part['text'], topic, candidates):
                    relevant.append((part['video'], x))

        if relevant:
            relevant_transformed = []
            for video_link, quotes in relevant:
                relevant_transformed.append({
                    "video": get_video(video_link),
                    "quotes": [{
                        "speaker": quote['speaker'],
                        "candidate": quote['speaker'] in debate['candidates'],
                        "question": quote['question'],
                        "time": quote['time'],
                        "text": quote['text']
                    } for quote in quotes]
                })

            results.append({
                "title": debate['title'],
                "date": debate['date'],
                "description": debate['description'],
                "results": relevant_transformed
            })
    return results


# tags are:
# one of: "debate", "town hall", "speech", "interview",
# hierarchy (only one of which):
#                                                   [year] election
#                           [year] presidential election         etc
# [year] democratic presidential primary       [year] republican presidential primary   [year] presidential general election