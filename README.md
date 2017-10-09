# losswise-python

To deploy new python package to PyPi do:

```shell
python setup.py sdist
python setup.py bdist_wheel --universal
twine upload dist/*
```
