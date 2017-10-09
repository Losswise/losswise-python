import threading
import json
import time
import requests
import random
from six.moves import queue
from six import iteritems
from threading import Thread


API_KEY = None
BASE_URL = 'https://api.losswise.com'
WARNINGS = True


def set_api_key(api_key):
    global API_KEY
    API_KEY = api_key


def set_base_url(base_url):
    global BASE_URL
    BASE_URL = base_url


queue = queue.Queue()
def worker():
    while True:
        (x, y, stats, time, graph_id, session_id) = queue.get()
        json_data = {
            'x': x,
            'y': y,
            'time': time,
            'graph_id': graph_id,
            'session_id': session_id,
            'stats': stats
        }
        json_message = json.dumps(json_data)
        url = BASE_URL + '/api/v1/points'
        headers = {"Authorization": API_KEY, "Content-type": "application/json"}
        # TODO: provide warning message is POST fails
        try:
            r = requests.post(url, data=json_message, headers=headers)
        except requests.exceptions.ConnectionError:
            if WARNINGS:
                print("Warning: request failed.")
        queue.task_done()


class Graph(object):
    def __init__(self, tracker, xlabel, ylabel, title, kind=None, max_iter=None):
        self.tracker = tracker
        self.kind = kind
        self.max_iter = max_iter
        json_data = {
            'session_id': self.tracker.session_id,
            'xlabel': xlabel,
            'ylabel': ylabel,
            'title': title,
            'kind': kind
        }
        json_message = json.dumps(json_data)
        r = requests.post(BASE_URL + '/api/v1/graphs',
                          data=json_message,
                          headers={"Authorization": API_KEY, "Content-type": "application/json"})
        json_resp = r.json()
        if json_resp['success'] is True:
            self.graph_id = r.json()['graph_id']
        else:
            error = json_resp['error']
            raise RuntimeError('Unable to create graph: %s' % (error,))
        # set up thread for tracking single events
        thread = Thread(target=worker)
        thread.daemon = True
        thread.start()
        self.thread = thread
        self.stats =  {}
        if kind not in ['min', 'max', None]:
            raise ValueError("'kind' variable must be 'min', 'max', or empty!")
        self.kind = kind

    def now(self):
        return time.time()

    def append(self, x, y):
        stats_update = {}
        data_new = y.copy()
        data_new['x'] = x
        if self.max_iter is not None:
            data_new['xper'] = min(1., (x + 1.) / self.max_iter)
        for key, val in iteritems(data_new):
            if key in ['x', 'xper']:
                kind = 'max'
            else:
                kind = self.kind
            if kind is None:
                continue
            val_old = self.stats.get(key, {}).get(kind, None)
            if val_old is None:
                val_new = val
            elif kind == 'max':
                val_new = max(val, val_old)
            elif kind == 'min':
                val_new = min(val, val_old)
            if val_new != val_old:
                stats_update[key] = { kind: val_new }
        self.stats.update(stats_update)
        if any(stats_update):
            stats = self.stats
        else:
            stats = {}
        queue.put((x, y, stats, int(self.now()), self.graph_id, self.tracker.session_id))

    def done(self):
        queue.join()


class Session(object):
    def __init__(self, tag, max_iter=None, data={}):
        self.api_key = API_KEY
        self.tag = tag
        self.max_iter = max_iter
        self.graph_list = []
        json_data = {
            'tag': tag,
            'data': data,
            'max_iter': max_iter
        }
        json_message = json.dumps(json_data)
        try:
            r = requests.post(BASE_URL + '/api/v1/sessions',
                              data=json_message,
                              headers={"Authorization": API_KEY, "Content-type": "application/json"})
        except requests.exceptions.ConnectionError:
            raise RuntimeError("Error: losswise connection tracker failed.  Please contact support@losswise.com")
        json_resp = r.json()
        if json_resp['success'] is True:
            self.session_id = json_resp['session_id']
        else:
            error = json_resp['error']
            raise RuntimeError('Unable to create session: %s.  Please contact support@losswise.com' % (error,))
        # start monitoring thread
        self.status = 'active'
        self.stop_event = threading.Event()
        def keepalive(stop_event):
            while not stop_event.is_set():
                json_message = json.dumps({'attributes' : {'status': self.status}})
                try:
                    r = requests.patch(BASE_URL + '/api/v1/sessions/' + self.session_id,
                                      data=json_message,
                                      headers={"Authorization": API_KEY, "Content-type": "application/json"})
                except requests.exceptions.ConnectionError:
                    if WARNINGS:
                        print("Warning: request failed.")
                time.sleep(30)
        self.thread = Thread(target=keepalive, args=(self.stop_event,))
        self.thread.daemon = True
        self.thread.start()

    def done(self):
        self.status = 'complete'
        self.stop_event.set()
        for graph in self.graph_list:
            graph.done()
        json_message = json.dumps({'attributes' : {'status': self.status}})
        try:
            r = requests.patch(BASE_URL + '/api/v1/sessions/' + self.session_id,
                              data=json_message,
                              headers={"Authorization": API_KEY, "Content-type": "application/json"})
        except requests.exceptions.ConnectionError:
            if WARNINGS:
                print("Warning: request failed.")

    def graph(self, title='', xlabel='', ylabel='', kind=''):
        assert kind in ['', 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel, kind=kind, max_iter=self.max_iter)
        self.graph_list.append(graph)
        return graph

    def Graph(self, title='', xlabel='', ylabel='', kind=''):
        assert kind in ['', 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel, kind=kind, max_iter=self.max_iter)
        self.graph_list.append(graph)
        return graph
