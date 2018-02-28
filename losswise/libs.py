from losswise import Session
from keras.callbacks import Callback


class LosswiseKerasCallback(Callback):
    def __init__(self, tag=None, params={}):
        # model hyper parameters, json serializable Python object
        self.tag = tag
        self.params_data = params
        self.graph_map = {}
        super(LosswiseKerasCallback, self).__init__()
    def on_train_begin(self, logs={}):
        if 'epochs' in self.params and 'samples' in self.params and 'batch_size' in self.params:
            self.max_iter = int(self.params['epochs'] * self.params['samples'] / self.params['batch_size'])
        elif 'steps_per_epoch' in self.params and 'epochs' in self.params:
            self.max_iter = self.params['steps_per_epoch'] * self.params['epochs']
        else:
            self.max_iter = None
        self.session = Session(tag=self.tag, max_iter=self.max_iter, params=self.params_data)
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
            self.graph_map[metric] = self.session.graph(metric, kind=kind)
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
