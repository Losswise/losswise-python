losswise-python
==============================

This is the official Losswise Python library. This library allows for
server-side integration of Losswise.


Installation
------------

The library can be installed using pip::

    pip install losswise


Getting Started
---------------

First create an account on the Losswise website (https://losswise.com).  This will automatically generate a unique API key.

Typical usage usually looks like this::

    import random
    import losswise

    # replace with your own api key
    losswise.set_api_key('your_api_key')

    # replace with a string that identifies your model
    session = losswise.Session(tag='my_dilated_convnet', max_iter=10, data={'num_params': 10000000})

    # create empty graph for loss, keep track of minima here hence kind='min'
    graph = session.graph(title='loss', kind='min')

    # track artificial loss over time
    for x in xrange(10):
        train_loss = 1. / (0.1 + x + 0.1 * random.random())
        test_loss = 1.5 / (0.1 + x + 0.2 * random.random())
        graph.append(x, {'train_loss': train_loss, 'test_loss': test_loss})

    # mark session as complete
    session.done()


You can then view the visualization results on your dashboard.

