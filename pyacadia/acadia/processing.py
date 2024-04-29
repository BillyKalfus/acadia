import logging
import os
import json
import inspect
from datetime import datetime, timezone
from typing import Union

import numpy as np

from acadia.data import DataManager, CounterRecordGroup

def process_data(source, dimensions=None):
    """
    A helper function for retrieving and processing data. 

    The parameter ``source`` specifies the origin of the data, depending 
    on its type:
    
    - If a tuple of (:class:`DataManager`, str), this indicates that data
        should be extracted from the :class:`DataManager` in the first 
        element using the record name given by the second.

    - If a :class:`RecordGroup`, this indicates that the data should be 
        extracted by calling that object's `records()` method.

    - If a :class:`np.ndarray`, this is used as the data directly.

    The retrieved data is always flattened, and the ``dimensions`` sequence
    parameter describes how it should be reshaped and processed. This must 
    contain one element per dimension of the reshaped data, and each element  
    must be a tuple with the following two elements:

    - An object specifying the length of the data in the dimension. If an 
        ``int``, this is used as the length. If an object defining 
        ``__len__``, its return value is used as the length of the 
        corresponding dimension. At most one dimension may use ``-1`` for
        this parameter, in which case the length of data in that dimension 
        is inferred via the amount of data available.

    - An object specifying how to reduce the data across the dimension. If
        ``None``, no reduction is performed and all data along the 
        corresponding dimension is returned. If an ``int``, the data at the
        corresponding index along the dimension's axis is used. If an 
        object defining ``__len__``, the data at the indices specified by 
        the elements of this parameter is used. If an object of type 
        ``np.ufunc``, the data is reduced along the corresponding dimension
        using the function. If an object defining ``__call__`` (which 
        isn't of type ``np.ufunc``), the object is called with the data 
        array provided as the first (and only) positional argument and 
        ``axis`` provided as the only keyword argument, populated with the
        axis number that this callable was provided for.

    """
    logger = logging.getLogger()

    if isinstance(source, tuple) and len(source) == 2 and isinstance(source[0], DataManager) and isinstance(source[1], str):
        data = source[0][source[1]].records()
    elif isinstance(source, np.ndarray):
        data = source
    else:
        raise TypeError(f"Unable to interpret data source {type(source)}")

    logger.debug(f"Processing data of type {data.dtype} with {data.size} elements")

    if dimensions is None:
        return data, data.shape
    
    if not hasattr(dimensions, "__len__"):
        raise TypeError(f"Dimension-specifying parameter must be sequence-like;"
                        f" found type {type(dimensions)}")
    
    if len(dimensions) == 0:
        return data, data.shape

    # Get rid of any partial datasets
    # If none of the lengths are -1, an extra dimension will be added
    dataset_shape = tuple(len(e) if hasattr(e, "__len__") else e for e,_ in dimensions)
    dataset_size = np.prod(dataset_shape)

    if dataset_size < 0:
        # One of the dimensions is -1
        # Here, we'll only use the total number of datasets to determine how many
        # elements we need to discard
        dataset_size *= -1
        num_datasets = data.size // dataset_size
        elements_to_keep = num_datasets*dataset_size
        return_data = data.reshape(-1)[:elements_to_keep].reshape(*dataset_shape)
    else:
        # Add a dimension to the beginning to index over complete datasets
        num_datasets = data.size // dataset_size
        elements_to_keep = num_datasets*dataset_size
        return_data = data.reshape(-1)[:elements_to_keep].reshape(num_datasets, *dataset_shape)

    shape_before_reduction = return_data.shape

    logger.debug(f"Found {num_datasets} datasets using shape {dataset_shape}"
                    f" (size {dataset_size}), with {data.size - elements_to_keep}"
                    f" elements left over. Final shape before reduction:"
                    f" {shape_before_reduction}")

    # Iterate in reverse order, since reducing over axes whose elements are
    # consecutive in memory will be much faster
    for axis,(_,reducer) in reversed(list(enumerate(dimensions))):
        if isinstance(reducer, np.ufunc):
            return_data = reducer.reduce(return_data, axis=axis)

            # Add back in the trivial axis that was reduced (so as not to 
            # confuse the axis numbers in following iterations)
            return_data = np.expand_dims(return_data, axis)
        elif isinstance(reducer, (int, list, tuple, np.ndarray)):
            return_data = np.take(return_data, reducer, axis=axis)
        elif hasattr(reducer, "__call__"):
            return_data = reducer(return_data, axis=axis)
        elif reducer is not None:
            raise TypeError(f"Unable to reduce dimension {axis} with object"
                            f" of type {type(reducer)}")

    return return_data, shape_before_reduction

# class DynamicFigure:
#     """
#     A helper class for adding dynamic plots rendered by ``matplotlib``.
#     """

#     def __init__(self, figure = None):
#         import matplotlib.pyplot as plt
#         from matplotlib.animation import Animation
#         from itertools import count

#         # TODO: figure out why things don't work if we call this here
#         # rather than in the runtime file itself
#         # from IPython.core.getipython import get_ipython
#         # get_ipython().run_line_magic("matplotlib", "widget")

#         self.fig = plt.figure() if figure is None else figure

#         def _init(anim_self: Animation, *args, **kwargs):
#             anim_self._framedata = count()
#             super(anim_self.__class__, anim_self).__init__(*args, **kwargs)

#         def _dummy(*args, **kwargs):
#             pass

#         test_animation_type = type(f"RuntimePyPlotAnimation", 
#                                 (Animation,), 
#                                 {"__init__": _init, 
#                                  "_draw_frame": _dummy})
        
#         DummyEvent = type("DummyEvent", (), {"add_callback": _dummy, "start": _dummy, "stop": _dummy})

#         self.anim = test_animation_type(self.fig, event_source=DummyEvent)
#         self.anim._step()
    
#     def update(self): 
#         self.anim._step()

#     def figure(self):
#         return self.fig

class DynamicFigure:
    """
    A helper class for adding dynamic plots rendered by ``matplotlib``.
    """

    def __init__(self, figure):
        self.fig = figure
    
    def update(self): 
        self.fig.canvas.draw_idle()

    def figure(self):
        return self.fig
            

class DynamicLine:
    """
    A simple wrapper for dynamically updating plots rendered by calls to 
    :meth:`Axes.plot()`.
    """

    def __init__(self, ax, fmt="-", **kwargs):
        """
        Add the line to a pyplot axis. All arguments (except for the axis) 
        will be passed directly to `Axes.plot()`

        :param ax: Axis to add to
        :type ax: matplotlib.pyplot.Axes
        """
        self._ax = ax
        self.retval = ax.plot([], [], fmt, **kwargs)

    def update(self, xdata, ydata, rescale_axis=True):
        """
        Update the data contained in a line created by calling `Axis.plot`. 
        
        :param plot_retval: Value returned by `plot`
        :type plot_retval: tuple
        """
        self.retval[0].set_data(xdata, ydata)
        if rescale_axis:
            xlim = self._ax.get_xlim()
            xmin = np.min(xdata)
            xmax = np.max(xdata)
            if (xmin != xlim[0] or xmax != xlim[1]) and xmin != xmax:
                self._ax.set_xlim(xmin, xmax)

            ylim = self._ax.get_ylim()
            ymin = np.min(ydata)
            ymax = np.max(ydata)
            if (ymin != ylim[0] or ymax != ylim[1]) and ymin != ymax:
                self._ax.set_ylim(ymin, ymax)

class DynamicErrorbar:

    def __init__(self, ax, fmt="-", **kwargs):
        """
        Add the line to a pyplot axis. All arguments (except for the axis) 
        will be passed directly to `Axes.plot()`

        :param ax: Axis to add to
        :type ax: matplotlib.pyplot.Axes
        """
        self.retval = ax.errorbar([], [], fmt, yerr=[], **kwargs)

    def update(self, xdata, ydata, yerr):
        """
        Update the curve and error data on an errorbar.
        """
        ln,err,bars = self.retval
        ln.set_data(xdata, ydata)
        
        new_errorbars = [[[x,ydata[i]-yerr[i]],
                          [x,ydata[i]+yerr[i]]] for i,x in enumerate(xdata)]
        
        bars[0].set_segments([np.array(points) for points in new_errorbars])

class DynamicPcolormesh:

    def __init__(self, ax, **kwargs):
        self.retval = ax.pcolormesh([], **kwargs)

    def update(self, x, y, data):
        """
        Update the values of the colormesh. Note that moving in the x-direction
        corresponds to moving from one row to the next; that is, a single 
        data point is given by data[x_idx, y_idx]. See the documentation for
        ``matplotlib.pyplot.pcolormesh`` for additional information.
        """
        
class ProgressBar:
    def __init__(self, label=None):        
        from tqdm.notebook import tqdm
        self.bar = tqdm(desc=label, dynamic_ncols=True)
        self._last_count = 0

    def update(self, group: CounterRecordGroup):
        """
        Update the progress bar from the value in a :class:`CounterRecordGroup`.
        """
        if self.bar.desc is None:
            self.bar.desc = group._name
            self.bar.refresh()

        if "total" in group.metadata():
            self.bar.total = group.total
            self.bar.refresh()

        self.bar.update(group.count - self._last_count)
        self._last_count = group.count
            
    def finalize(self):
        self.bar.close()

class Database:
    """
    A class for managing persistent storage of data. This is primarily intended
    to be used for automatically extracting and updating calibration values in 
    relevant experiments. Despite being called a database and functioning as 
    one, each instance is backed by a JSON file to enable human-readability.
    """

    def __init__(self, path="/tmp"):
        """
        Create or open a database file. If ``path'' is a directory, a new 
        database file is created in the directory and if ``path'' is a file,
        the file is opened. If the file does not exist, it is created.
        """
        if os.path.isdir(path):
            time_str = datetime.now(timezone.utc).strftime("%m%d%y-%H%M%S")
            self._filename = os.path.join(path, f'db-{time_str}.json')
        else:
            self._filename = path

        self.reload()

    def save(self):
        """
        Commit the current values stored in this instance to file.
        """
        with open(self._filename, "w") as f:
            json.dump(self._data, f)

    def reload(self):
        """
        Reload the internally-stored values from the file.
        """
        if os.path.exists(self._filename) and os.path.getsize(self._filename) > 0:
            with open(self._filename, "r") as f:
                self._data = json.load(f)
            if not isinstance(self._data, dict):
                raise TypeError(f"Database initialized with object of type {type(self._data)}")
        else:
            self._data = {}

    def __getitem__(self, key):
        return self._data[key]
    
    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data
    
    def keys(self):
        return self._data.keys()
    
    def values(self):
        return self._data.values()
    
    def items(self):
        return self._data.items()

    @staticmethod
    def extract(func: callable, data, keys: list = None) -> dict:
        """
        Extract values from a dict or database for populating the keyword 
        arguments of a function. 
        
        Because the database is meant to hold arbitrary data, it could contain
        many more entries than there are keywords arguments in the function to 
        be populated. This method extracts only the allowed arguments and 
        creates a new dict that can be safely expanded into the function call.

        The ``data'' parameter specifies the entity from which to extract 
        argument values. By default, as many keywords as possible are 
        extracted; alternatively, a subset of
        keywords to populate can be specified with ``keys''. 
        """
        args,_,_,_ = inspect.getargspec(func)

        d = {}
        for key in (keys if keys is not None else args):
            if key in data:
                d[key] = data[key]
        
        return d
        
class ClusterDisplay:
    """
    A class for displaying complex histograms of collected spectroscopy data, 
    identifying clusters by fitting to a Gaussian mixture model, and computing 
    the optimal linear filters for separating two of the clusters. 
    """

    def __init__(self, clusters: int = 2, iterations: int = 100):
        """
        :param clusters: Number of clusters to identify
        :type clusters: int
        :param iterations: Number of optimization iterations
        :type iterations: int
        """

        self._clusters = clusters

        from hmmlearn.hmm import GaussianHMM
        self._model = GaussianHMM(n_components=clusters, covariance_type="full", n_iter=iterations)

    def update(self, data: np.ndarray):
        """
        :param data: Data to fit
        :type data: numpy.ndarray with complex datatype
        """            
        data_stacked = data.astype(f"<f{data.itemsize // 2}").reshape(-1,2)
        self._model.fit(data_stacked)



        
