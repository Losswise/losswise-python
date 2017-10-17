from losswise import Session
from keras.callbacks import Callback


class LosswiseKerasCallback(Callback):
    def __init__(self, tag=None, max_iter=None, use_acc=False, use_val=False, data={}, git_model_path=None):
        self.session = Session(tag=tag, max_iter=max_iter, data=data, git_model_path=git_model_path)
        self.use_acc = use_acc
        self.use_val = use_val
        self.graph_loss = self.session.graph('loss', kind='min')
        self.graph_acc = None
        self.max_iter = max_iter
        if use_acc:
            self.graph_acc = self.session.graph('acc', kind='max')
        super(LosswiseKerasCallback, self).__init__()
    def on_train_begin(self, logs={}):
        self.x = 0
    def on_batch_end(self, batch, logs={}):
        if self.use_val:
            self.graph_loss.append(self.x, {'train_loss': logs.get('loss'),
                                            'val_loss': logs.get('val_loss')})
        else:
            self.graph_loss.append(self.x, {'train_loss': logs.get('loss')})
        if self.use_acc:
            if self.use_val:
                self.graph_acc.append(self.x, {'train_acc': logs.get('acc'),
                                               'val_acc': logs.get('val_acc')})
            else:
                self.graph_acc.append(self.x, {'train_acc': logs.get('acc')})
        self.x += 1
    def on_train_end(self, logs={}):
        self.session.done()
