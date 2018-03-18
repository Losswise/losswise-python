import os
import threading
import json
import time
import requests
import random
import math
from six.moves import queue
from six import iteritems
import subprocess
from threading import Thread
import re


API_KEY = None
BASE_URL = 'https://api.losswise.com'
WARNINGS = True


def set_api_key(api_key):
    global API_KEY
    API_KEY = api_key


def set_base_url(base_url):
    global BASE_URL
    BASE_URL = base_url


def get_git_info():
    git_info = {'diff' : '', 'branch': '', 'url': ''}
    try:
        FNULL = open(os.devnull, 'w')
        git_info['diff'] = str(subprocess.Popen(['git', 'diff'],
                               stdout=subprocess.PIPE, stderr=FNULL).communicate()[0])
        git_info['branch'] = str(subprocess.Popen(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                                 stdout=subprocess.PIPE, stderr=FNULL).communicate()[0].replace('\n', ''))
        git_remote = str(subprocess.Popen(['git', 'remote', '-v'],
                         stdout=subprocess.PIPE, stderr=FNULL).communicate()[0].split("  ")[0])
        git_info['url'] = re.findall('\S*\.git', git_remote)[0]
    except Exception as e:
        pass
    return git_info


work_queue = queue.Queue()
def worker():
    while True:
        point_list = []
        stats_map = {}
        while not work_queue.empty() or len(point_list) == 0:
            (x, y, stats, t, graph_id, session_id) = work_queue.get()
            json_data = {
                'x': x,
                'y': y,
                'time': t,
                'graph_id': graph_id,
                'session_id': session_id,
            }
            if any(stats):
                stats_map[graph_id] = stats
            point_list.append(json_data)
        json_message = json.dumps({'point_list': point_list, 'stats_map': stats_map})
        url = BASE_URL + '/api/v1/point-list'
        headers = {"Authorization": API_KEY, "Content-type": "application/json"}
        try:
            r = requests.post(url, data=json_message, headers=headers)
        except requests.exceptions.ConnectionError:
            if WARNINGS:
                print("Warning: request failed.")
        except Exception as e:
            if WARNINGS:
                print(e)
        for _ in range(len(point_list)):
            work_queue.task_done()


event_thread = Thread(target=worker)
event_thread.daemon = True
event_thread.start()


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
        self.stats =  {}
        if kind not in ['min', 'max', None]:
            raise ValueError("'kind' variable must be 'min', 'max', or empty!")
        self.kind = kind
        self.x = 0

    def now(self):
        return time.time()

    def append(self, *args):
        if len(args) == 1:
            x = self.x
            y_raw = args[0]
        elif len(args) == 2:
            x = args[0]
            y_raw = args[1]
        else:
            raise ValueError("Append method only accepts one or two arguments.")
        stats_update = {}
        y = {}
        for key, val in iteritems(y_raw):
            if math.isnan(val):
                print("Warning: skipping '%s' due to NaN value." % key)
                continue
            y[key] = float(y_raw[key])
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
        work_queue.put((x, y, stats, int(self.now()), self.graph_id, self.tracker.session_id))
        self.x = self.x + 1


class Session(object):
    def __init__(self, tag=None, max_iter=None, params={}, track_git=True):
        self.graph_list = []
        self.max_iter = max_iter
        self.api_key = API_KEY
        git_info = get_git_info()
        self.tag = 'default'
        if tag is None:
            if 'BUILDKITE_BRANCH' in os.environ:
                self.tag = os.environ['BUILDKITE_BRANCH']
            elif git_info.get('branch', None) is not None:
                if len(git_info['branch'].replace(" ", "")) > 0:
                    self.tag = git_info['branch']
        else:
            self.tag = tag
        json_data = {
            'tag': self.tag,
            'params': params,
            'max_iter': max_iter,
            'env': {}
        }
        if track_git:
            json_data['git'] = git_info
        for env_var in ['BUILDKITE_BUILD_URL', 'BUILDKITE_REPO',
                        'BUILDKITE_PIPELINE_PROVIDER', 'BUILDKITE_BRANCH']:
            if env_var in os.environ:
                json_data['env'][env_var] = os.environ[env_var]
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
                except Exception as e:
                    if WARNINGS:
                        print(e)
                time.sleep(30)
        self.thread = Thread(target=keepalive, args=(self.stop_event,))
        self.thread.daemon = True
        self.thread.start()

    def done(self):
        self.status = 'complete'
        self.stop_event.set()
        work_queue.join()
        json_message = json.dumps({'attributes' : {'status': self.status}})
        try:
            r = requests.patch(BASE_URL + '/api/v1/sessions/' + self.session_id,
                              data=json_message,
                              headers={"Authorization": API_KEY, "Content-type": "application/json"})
        except requests.exceptions.ConnectionError:
            if WARNINGS:
                print("Warning: request failed.")
        except Exception as e:
            if WARNINGS:
                print(e)

    def graph(self, title='', xlabel='', ylabel='', kind=None):
        assert kind in [None, 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel, kind=kind, max_iter=self.max_iter)
        self.graph_list.append(graph)
        return graph

    def Graph(self, title='', xlabel='', ylabel='', kind=None):
        assert kind in [None, 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel, kind=kind, max_iter=self.max_iter)
        self.graph_list.append(graph)
        return graph
