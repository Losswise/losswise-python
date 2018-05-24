from losswise import Session
from keras.callbacks import Callback


class LosswiseKerasCallback(Callback):
    def __init__(self, tag=None, params={}, track_git=True, display_interval=None, max_iter=None):
        # model hyper parameters, json serializable Python object
        self.tag = tag
        if not isinstance(params, dict):
            raise TypeError("\"params\" argument must be a valid python dictionary")
        if tag is not None and not isinstance(tag, str):
            raise TypeError("\"tag\" argument must be a valid python string")
        self.params_data = params
        self.track_git = track_git
        self.graph_map = {}
        self.display_interval = display_interval
        self.max_iter = max_iter
        super(LosswiseKerasCallback, self).__init__()
    def on_train_begin(self, logs={}):
        if self.max_iter is None:
            if 'epochs' in self.params and 'samples' in self.params and 'batch_size' in self.params:
                self.max_iter = int(self.params['epochs'] * self.params['samples'] / self.params['batch_size'])
            elif 'steps_per_epoch' in self.params and 'epochs' in self.params:
                self.max_iter = self.params['steps_per_epoch'] * self.params['epochs']
            elif 'samples_per_epoch' in self.params and 'epochs' in self.params:
                self.max_iter = self.params['samples_per_epoch'] * self.params['epochs']
            elif 'steps' in self.params and 'epochs' in self.params:
                self.max_iter = self.params['steps'] * self.params['epochs']
            else:
                print("Warning: Please specify max_iter!")
                print("You have not set max_iter, for example do LosswiseKerasCallback(..., max_iter=10000)")
        self.session = Session(tag=self.tag, max_iter=self.max_iter, params=self.params_data,
                               track_git=self.track_git)
        self.metric_list = []
        for metric in self.params['metrics']:
            if not metric.startswith('val_'):
                if metric not in self.metric_list:
                    self.metric_list.append(metric)
        for metric in self.metric_list:
            if 'acc' in metric:
                kind = 'max'
            else:
                kind = 'min'
            self.graph_map[metric] = self.session.graph(metric, kind=kind, display_interval=self.display_interval)
        self.x = 0
    def on_epoch_end(self, epoch, logs={}):
        for metric in self.metric_list:
            metric_val = "val_" + metric
            if metric_val in logs:
                data = {metric_val: logs[metric_val]}
                self.graph_map[metric].append(self.x, data)
    def on_batch_end(self, batch, logs={}):
        for metric in self.metric_list:
            data = {metric: logs.get(metric)}
            self.graph_map[metric].append(self.x, data)
        self.x += 1
    def on_train_end(self, logs={}):
        self.session.done()
