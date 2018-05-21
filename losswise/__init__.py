import sys
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
import base64
import io


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
        size_mb = sys.getsizeof(git_info['diff']) / 1000000.
        if size_mb > 0.2:
            git_info['diff'] = "git diff too large to show here"
            print("Losswise warning: git diff too large to track.")
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
    def __init__(self, tracker, xlabel, ylabel, title, kind=None, max_iter=None, display_interval=None):
        self.tracker = tracker
        self.kind = kind
        self.max_iter = max_iter
        if display_interval is not None:
            self.display_interval = display_interval
        else:
            if max_iter is None:
                print("Losswise warning: please set max_iter or display_interval for optimal user experience.")
                print("Losswise will track all points without smoothing.")
                self.display_interval = 1
            else:
                self.display_interval = max(1, max_iter // 200)
            print("Losswise: choosing optimal display_interval = %d for \"%s\" graph." % (self.display_interval, title))
            print("You may override this default behavior by manually setting display_interval yourself.")
        json_data = {
            'session_id': self.tracker.session_id,
            'xlabel': xlabel,
            'ylabel': ylabel,
            'title': title,
            'kind': kind,
            'display_interval': display_interval
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
            error_msg = 'Unable to create graph: %s' % error
            raise RuntimeError(error_msg)
        self.tracked_value_map = {}
        self.stats =  {}
        if kind not in ['min', 'max', None]:
            raise ValueError("'kind' variable must be 'min', 'max', or empty!")
        self.kind = kind
        self.x = 0

    def now(self):
        return time.time()

    def append(self, *args):
        if len(args) == 1:
            x = int(self.x)
            y_raw = args[0]
        elif len(args) == 2:
            x = int(args[0])
            y_raw = args[1]
        else:
            raise ValueError("Append method only accepts one or two arguments.")
        stats_update = {}
        y = {}
        for key, val in iteritems(y_raw):
            if math.isnan(val):
                print("Warning: skipping '%s' due to NaN value." % key)
                continue
            if key in self.tracked_value_map:
                tracked_value_list = self.tracked_value_map[key]
                tracked_value_list.append((x, val))
                if self.max_iter is not None and x < self.max_iter - 1 and x % self.display_interval != 0:
                    return
                tracked_value_len = len(tracked_value_list)
                diff = tracked_value_list[tracked_value_len - 1][0] - tracked_value_list[tracked_value_len - 2][0]
                if diff == 1 and tracked_value_len >= self.display_interval > 1:
                    xy_tuple_values = tracked_value_list[-self.display_interval:]
                    y_values = [xy_tuple[1] for xy_tuple in xy_tuple_values]
                    y_smooth = sum(y_values) / len(y_values)
                    y[key] = float(y_smooth)
                else:
                    y[key] = float(y_raw[key])
                    self.tracked_value_map[key] = [(x, val)]
                if len(tracked_value_list) > 3 * self.display_interval:
                    del tracked_value_list[:self.display_interval]
            else:
                y[key] = float(y_raw[key])
                self.tracked_value_map[key] = [(x, val)]
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
                stats_update[key] = {kind: val_new}
        self.stats.update(stats_update)
        if any(stats_update):
            stats = self.stats
        else:
            stats = {}
        work_queue.put((x, y, stats, int(self.now()), self.graph_id, self.tracker.session_id))
        self.x = self.x + 1


class ImageSequence(object):
    def __init__(self, session_id, x, name):
        json_data = {"session_id": session_id, "name": name, "x": x, "type": "image"}
        json_message = json.dumps(json_data)
        self.prediction_sequence_id = None
        try:
            r = requests.post(BASE_URL + '/api/v1/prediction-sequences',
                              data=json_message,
                              headers={"Authorization": API_KEY, "Content-type": "application/json"})
            json_resp = r.json()
        except Exception as e:
            print(e)
            return
        if json_resp.get('success', False) is True:
            self.prediction_sequence_id = json_resp["prediction_sequence_id"]
        else:
            error = json_resp.get('error', '')
            error_msg = 'Unable to create image sequence: %s' % error
            print(error_msg)

    def append(self, image_pil, image_id='', outputs={}, metrics={}):
        if self.prediction_sequence_id is None:
            print("Skipping append due to failed create image sequence API call.")
            return
        image_buffer = io.BytesIO()
        try:
            image_pil.save(image_buffer, format='PNG')
        except AttributeError as e:
            print("Unable to save image as PNG! Make sure you're using a PIL image.")
            return
        contents = image_buffer.getvalue()
        image_buffer.close()
        image_data = base64.b64encode(contents).decode('utf-8')
        json_data = {"prediction_sequence_id": self.prediction_sequence_id,
                        "image": image_data,
                        "metrics": metrics,
                        "outputs": outputs,
                        "image_id": image_id}
        json_message = json.dumps(json_data)
        try:
            r = requests.post(BASE_URL + '/api/v1/image-prediction',
                              data=json_message,
                              headers={"Authorization": API_KEY, "Content-type": "application/json"})
            json_resp = r.json()
            err = json_resp.get("error", None)
            if json_resp['success'] is False and err:
                print ("Request failed! " + err)
        except requests.exceptions.ConnectionError:
            if WARNINGS:
                print("Warning: request failed due to connection error.")
        except Exception as e:
            if WARNINGS:
                print("Warning: POST request failure.")
                print(e)


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
            error_msg = 'Unable to create session: %s. Please contact support@losswise.com' % error
            raise RuntimeError(error_msg)
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
                time.sleep(10)
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

    def image_sequence(self, x, name=''):
        seq = ImageSequence(self.session_id, x, name)
        return seq

    def graph(self, title='', xlabel='', ylabel='', kind=None, display_interval=None):
        assert kind in [None, 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel,
                      kind=kind, max_iter=self.max_iter, display_interval=display_interval)
        self.graph_list.append(graph)
        return graph

    def Graph(self, title='', xlabel='', ylabel='', kind=None, display_interval=None):
        assert kind in [None, 'min', 'max']
        graph = Graph(self, title=title, xlabel=xlabel, ylabel=ylabel,
                      kind=kind, max_iter=self.max_iter, display_interval=self.display_interval)
        self.graph_list.append(graph)
        return graph
