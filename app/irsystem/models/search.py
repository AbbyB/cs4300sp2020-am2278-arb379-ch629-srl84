from datetime import datetime, timedelta

import pymongo
import spacy
from nltk.stem.snowball import SnowballStemmer

from app.irsystem import TYPE_TAGS
from app.irsystem.models.videos import get_video
from . import *

# test topics
# 'healthcare', 'terrorism', 'national security', 'gun policy', 'taxes',
# 'education', 'economy', 'immigration', 'abortion', 'federal deficit',
# 'climate change', 'environment', 'war', 'corona virus', 'covid 19'


nlp = spacy.load('en_core_web_sm')
stemmer = SnowballStemmer('english')


def get_score(text, topics, topic_expansion, topic_tree):
    score_t = {topic: text.lower().count(topic) for topic in topics}
    score_te = {topic: text.lower().count(topic) for topic in topic_expansion}

    # some topic expansions are in topics so don't double count those
    if topic_expansion:
        for t, tree in topic_tree.items():
            for te in tree:
                score_te[te] -= score_t[t]

    # score = sum(text.lower().count(topic) for topic in topics)
    # score += sum(text.lower().count(topic) for topic in topic_expansion) / 2
    return sum(score_t.values()) + sum(score_te.values()) / 2


# if i is in result, return the exchange
# otherwise, create a new one
def get_exchange(i, transcript, added, result, topics, topic_expansion, topic_tree):
    if i in result:
        return i, result[i]
    elif i in added:
        # must be a response
        return get_exchange(transcript[i]['response'], transcript, added, result, topics, topic_expansion, topic_tree)
    else:
        # new, add parent
        added.add(i)
        score = get_score(transcript[i]['text'], topics, topic_expansion, topic_tree)
        result[i] = ([transcript[i]], score)
        return i, result[i]


def exact_search(transcript, topics, topic_expansion, topic_tree):
    added = set()
    result = dict()
    for i, quote in enumerate(transcript):
        if i not in added:
            # if in questions, then add question and all responses
            if quote['question'] and quote['response']:
                score = get_score(quote['text'], topics, topic_expansion, topic_tree) * 2
                if score > 0:
                    exchange = [quote]
                    added.add(i)
                    for i2, q in enumerate(quote['response']):
                        # if same speaker is continuing
                        if len(exchange) > 1 and transcript[q]['speaker'] == exchange[-1]['speaker']:
                            # uninterrupted
                            if i2 > 0 and transcript[quote['response'][i2-1]]['text'] in exchange[-1]['text']:
                                exchange[-1]['text'] += ' ' + transcript[q]['text']
                            # interrupted
                            else:
                                exchange[-1]['text'] += ' ... ' + transcript[q]['text']
                        else:
                            exchange.append(transcript[q])
                        score += get_score(transcript[q]['text'], topics, topic_expansion, topic_tree)
                        added.add(q)
                    result[i] = (exchange, score)
            # otherwise only add question (if not already) and response
            elif not quote['question'] and type(quote['response']) != list:
                new_score = get_score(quote['text'], topics, topic_expansion, topic_tree)
                if new_score > 0:
                    added.add(i)
                    if quote['response'] is None:
                        first_i = i
                        exchange = []
                        score = 0
                    else:
                        first_i, (exchange, score) = get_exchange(quote['response'], transcript, added, result, topics, topic_expansion, topic_tree)
                    # if same speaker is continuing
                    if len(exchange) > 1 and quote['speaker'] == exchange[-1]['speaker']:
                        # uninterrupted
                        if i > 0 and transcript[i-1]['text'] in exchange[-1]['text']:
                            exchange[-1]['text'] += ' ' + quote['text']
                        # interrupted
                        else:
                            exchange[-1]['text'] += ' ... ' + quote['text']
                    else:
                        exchange.append(quote)
                    result[first_i] = (exchange, score + new_score)

    return result.values()


def query_expansion(topics): 
    expansion = []
    for topic in topics:
        tokens = topic.split()
        for token in tokens:
            if len(tokens) > 1: 
                expansion.append(token)
            if token in term_dictionary:
                expansion.extend([term_dictionary[token][i] for i in range(3)])
    return set(expansion)


# tokenize, lemmatize, lowercase, and filter out stop words and punctuation
def tokenize(text):
    tokens = {stemmer.stem(token.text.lower()) for token in nlp(text) if not (token.is_punct or token.is_space or token.is_stop)}
    return tokens


def get_candidate_info(candidate_name, election, date):
    # get polling data
    polls = db.polls.find_one({'candidate_race': candidate_name + '_' + election})
    if polls is not None:
        polls = sorted(polls['polls'], key=lambda x: x['date'], reverse=True)

        shifted_date = date + timedelta(days=1)  # day of polling won't be affected
        pre_date = date - timedelta(weeks=2)
        after_date = date + timedelta(weeks=2)

        # limit after_date to before next debate
        other_debates = db.debates.find_one({'candidates': candidate_name,
                                             'tags': 'debate',
                                             'date': {'$gt': date, '$lt': after_date}},
                                            sort=[('date', pymongo.ASCENDING)])
        if other_debates is not None:
            after_date = other_debates['date']

        # get the closest poll to before the debate and after roughly 4 weeks
        before = next((x for x in polls if pre_date <= x['date'] < shifted_date), False)
        after = next((x for x in polls if shifted_date <= x['date'] <= after_date), False)

        relevant_polls = [x for x in polls[::-1] if date - timedelta(weeks=4) <= x['date'] <= date + timedelta(weeks=4)]
        if before and after and before['pct'] != 0:
            pct_change = round((after['pct'] - before['pct']) / before['pct'] * 100, 2)
            return {'name': candidate_name, 'pct_change': pct_change, 'polls': relevant_polls}
        else:
            # can't calculate change if no polls in the range
            return {'name': candidate_name, 'pct_change': None, 'polls': relevant_polls}

    return {'name': candidate_name, 'pct_change': None, 'polls': []}


def sort_debates(debate, candidates):
    # order by number of searched candidates that were returned
    quote_speakers = {c['speaker'] for r in debate['results'] for c in r['quotes']}
    response_candidates = len(quote_speakers.intersection(candidates))

    # then order by combination of time since debate and total score of quotes
    half_years = (datetime.now() - debate['date']).days // 180 + 1
    date_score = debate['total_score'] / half_years

    return response_candidates, date_score


def search(topics, candidates, debate_filters, exact):
    # query: (OR candidates) AND (OR filters in title, tags, and description)

    topics = [topic.lower() for topic in topics]
    topic_expansion = query_expansion(topics)
    if exact:
        topic_expansion = set()
    topic_tree = {topic: [te for te in topic_expansion if te in topic] for topic in topics}

    # OR all of the candidates
    if len(candidates) == 0:
        debate_query = {'tags': 'debate'}
    elif len(candidates) == 1:
        debate_query = {'candidates': candidates[0]}
    else:
        debate_query = {'$or': [{'candidates': candidate} for candidate in candidates]}

    # AND all words in a debate filter, OR the filters
    debates = list(db.debates.find(debate_query))
    if not debate_filters:
        filtered_debates = debates
    else:
        filtered_debates = []

        title_filters = set(x['title'] for x in debates if x['title'] in debate_filters)
        other_filters = [x for x in debate_filters if x not in title_filters]
        for debate in debates:
            if debate['title'] in title_filters:
                filtered_debates.append(debate)
            else:
                # filter debates by title, tags, and description
                debate_text = tokenize(debate['title']).union(
                    tokenize(debate['description'])).union(
                    tokenize(' '.join(debate['tags'])))

                for debate_filter in other_filters:
                    words = tokenize(debate_filter)
                    if words.issubset(debate_text):
                        filtered_debates.append(debate)
                        break

    results = []
    for debate in filtered_debates:
        result = search_debate(debate, topics, topic_expansion, topic_tree)
        if result is not None:
            election = next(x for x in debate['tags'] if x not in TYPE_TAGS)
            result['candidates'] = [get_candidate_info(x, election, debate['date']) for x in debate['candidates']]
            result['candidates'].sort(key=lambda x: x['polls'][-1]['pct'] if x['polls'] else 0, reverse=True)
            results.append(result)
            result['is_polling'] = True if sum([len(x['polls']) for x in result['candidates']]) else False

    # order the debates
    candidates = set(candidates)
    results.sort(key=lambda x: sort_debates(x, candidates), reverse=True)

    # make dates pretty
    for debate in results:
        debate['date'] = f"{debate['date']:%B} {debate['date'].day}, {debate['date'].year}"

    return results, topics + list(topic_expansion)


def search_debate(debate, topics, topic_expansion, topic_tree):
    relevant = []

    for part in debate['parts']:
        for x, score in exact_search(part['text'], topics, topic_expansion, topic_tree):
            relevant.append((part['video'], x, score))

    if relevant:
        relevant_transformed = []
        relevant.sort(key=lambda x: x[2], reverse=True)
        total_score = 0
        for video_link, quotes, score in relevant:
            total_score += score
            relevant_transformed.append({
                'video': get_video(video_link),
                'quotes': [{
                    'speaker': quote['speaker'],
                    'candidate': quote['speaker'] in debate['candidates'],
                    'question': quote['question'],
                    'time': quote['time'],
                    'text': quote['text']
                } for quote in quotes]
            })

        return {
            'title': debate['title'],
            'date': debate['date'],
            'description': debate['description'],
            'tags': debate['tags'],
            'results': relevant_transformed,
            'total_score': total_score
        }
    return None
