import logging
import os
import json
import inspect
from datetime import datetime, timezone
from typing import Union

import numpy as np

from acadia.data import DataManager
from acadia.arrays import Waveform

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

# class LinePlot:
#     """
#     A helper class for generating dynamically updating line plots.
     
#     This simplifies the process of extracting data from 
#     :class:`ArrayRecordGroup` objects stored in a :class:`DataManager`. This
#     class builds on top of :class:`PyPlotRuntimeComponent` by allowing the user
#     to specify update
#     behavior by describing future array processing in terms of the arguments to 
#     :meth:`ArrayRecordGroup.process_data`, rather than calling a fully generic 
#     callback function in a bespoke subclass of :class:`PyPlotRuntimeComponent`. 
#     This is primarily intended to reduce code duplication for simple cases, such
#     as creating plots where the data are stored directly in record groups and 
#     require only a limited amount of processing (if any), which is a common 
#     use-case.
#     """

#     def add_line(self, xdata, ydata, **kwargs):
#         """
#         Add a line to the plot. Two parameters are used for describing how the
#         xdata and ydata will be derived from the multi-dimensional data 
#         stored in a record, and the remaining arguments are passed 
#         directly to :meth:`Axes.plot()`. 
        
#         The parameters ``xdata`` and ``ydata`` describe the two axes of data 
#         to be plotted. If these are of type ``dict``, they will be expanded 
#         into keyword arguments for ``RuntimeComponent.retrieve_data()``; see
#         the corresponding documentation for a description of parameters. 
#         Otherwise, they will be passed as the ``source`` parameter.
#         """
#         if not hasattr(self, "_lines"):
#             self._lines = []

#         self._lines.append(
#             {"xdata": xdata if isinstance(xdata, dict) else {"source": xdata},
#              "ydata": ydata if isinstance(ydata, dict) else {"source": ydata}}
#         )
#         self._lines[-1].update(kwargs)

class DynamicFigure:
    """
    A helper class for adding dynamic plots rendered by ``matplotlib``.
    """

    def __init__(self, figure = None):
        import matplotlib.pyplot as plt
        from matplotlib.animation import Animation
        from itertools import count

        # from IPython.core.getipython import get_ipython
        # get_ipython().run_line_magic("matplotlib", "widget")

        if figure is None:
            figure = plt.figure()

        self.callbacks = []

        def _init(anim_self: Animation, *args, **kwargs):
            anim_self._framedata = count()
            super(anim_self.__class__, anim_self).__init__(*args, **kwargs)

        def _dummy(*args, **kwargs):
            pass

        test_animation_type = type(f"RuntimePyPlotAnimation", 
                                (Animation,), 
                                {"__init__": _init, 
                                 "_draw_frame": _dummy})
        
        DummyEvent = type("DummyEvent", (), {"add_callback": _dummy, "start": _dummy, "stop": _dummy})

        self.anim = test_animation_type(figure, event_source=DummyEvent)
        self.anim._step()
    
    def update(self): 
        self.anim._step()

    def figure(self):
        return self.fig

# class DynamicSubplots:
#     """
#     A helper class for adding dynamic plots rendered by ``matplotlib``.
#     """

#     def __init__(self, *args, **kwargs):
#         """
#         Create a new figure and subplots, along with extra infrastructure for
#         dynamically updating the plot. All arguments are passed directly into
#         :meth:`pyplot.subplots()`.
#         """
#         from IPython.display import display
#         from IPython.core.getipython import get_ipython

#         get_ipython().run_line_magic("matplotlib", "widget")

#         import matplotlib.pyplot as plt
#         from ipywidgets import Output
        
#         self.output = Output()
#         with self.output:
#             self.figure, self.ax = plt.subplots(*args, **kwargs)
#         display(self.output)
#         # display(self.figure)
    
#     def update(self): 
#         from IPython.display import display
#         self.figure.canvas.draw()
#         self.output.clear_output(wait=True)
#         with self.output:
#             display(self.figure)
            

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


# class ProgressBar:
#     def __init__(self):        
#         from tqdm.notebook import tqdm
#         self.bar = tqdm(desc=self._record_name, dynamic_ncols=True)
#         self._last_count = 0

#     def update(self, *args, **kwargs):
#         group = self.runtime.data[self._record_name]
#         if "total" in group.metadata():
#             self.bar.total = group.total
#             self.bar.refresh()

#         self.bar.update(group.count - self._last_count)
#         self._last_count = group.count
            
#     def finalize(self):
#         self.update()
#         self.bar.close()

    
# class SweptWaveformInterface:
#     """
#     An interactive interface for viewing swept waveform data.

#     Many experiments simply involve sweeping some parameter set over a grid of
#     values and collecting a waveform at each point. This class is primarily a
#     helper class to create a user-friendly means of viewing the captured data.

#     If the record group provided by ``capture_record_name`` has a metadata entry
#     with the name ``capture_time``, this is used to convert the x-axis into units
#     of seconds. Otherwise, units of samples are used.
#     """

#     def __init__(self, 
#                  data: DataManager, 
#                  capture_record_name: str, 
#                  sweep_record_names: list[str]):
#         """
#         :param: The :class:`DataManager` containing the capture data and the 
#             values of the sweep axes.
#         """
#         self._data = data
#         self._capture_record_name = capture_record_name
#         self._sweep_record_names = sweep_record_names
#         self._widgets_created = False

#         self._plot_retval = self._create_plot()

#     def update(self):
#         # Do nothing if we have no data
#         if not self._data.available(self._capture_record_name, *self._sweep_record_names):
#             return
        
#         # Create all the widgets only once we have all the data
#         # so that all the sliders have the correct axes
#         if not self._widgets_created:
#             self._widgets = self._create_widgets(self._data, self._sweep_record_names)
#             self._widgets_created = True
            
#         # Either take the mean of all the iterations or select a single one,
#         # depending on the input from the widgets
#         data = self._process_iterations(self._widgets, self._data, self._capture_record_name, self._sweep_record_names)

#         # Convert samples to complex numbers
#         traces = Waveform.to_complex(data)

#         # Create a time axis for convenience
#         time_axis = self._get_time_axis(self._data, self._capture_record_name)
#         sweep_axes = [self._data[r].records() for r in self._sweep_record_names]
#         self._update_plot(self._plot_retval, traces, time_axis, sweep_axes)

#     def _create_plot(self):
#         import matplotlib.pyplot as plt        
#         from acadia.processing import DynamicLine

#         fig,ax = plt.subplots(1, 1, figsize=(10,3))
#         fig.set_size_inches(10,3)
        
#         # Create a plot for the raw traces
#         self.re = DynamicLine(ax, ".-", label="Re")
#         self.im = DynamicLine(ax, ".-", label="Im")
#         ax.set_xlabel("Time [s]")
#         ax.set_ylabel("Signal Amplitude [arb. V]")
#         ax.set_title("Raw Data")
#         ax.legend()
#         ax.grid()

#         return fig,ax

#     def _create_widgets(self, 
#                         data: DataManager, 
#                         sweep_record_names: list[str]) -> dict[str]:
#         """
#         Create many widgets for interactively viewing the data
#         """
#         from IPython.display import display
#         from ipywidgets import SelectionSlider, VBox, IntSlider, RadioButtons

#         # Create all the widgets that control the plot view
#         widgets = {}

#         # Create a way for the user to choose whether they want to view the mean
#         # of all the iterations, or just a single one
#         widgets["iteration_selector"] = RadioButtons(options=["Mean", "Single iteration"], 
#                                                description="View data for:", 
#                                                disabled=False)
#         widgets["iteration_selector"].observe(self.update)

#         # Make a slider that will allow the user to choose an iteration to view, 
#         # when they want to view individual ones instead of the mean
#         widgets["iteration_slider"] = IntSlider(min=0, max=0, 
#                                                 disabled=True, 
#                                                 description="Iteration")
#         widgets["iteration_slider"].observe(self.update)

#         # Create sliders that allow the user to pick which sweep point they want to view
#         for record_name in sweep_record_names:
#             k = f"{record_name}_slider"
#             widgets[k] = SelectionSlider(options=list(data[record_name].records()), 
#                                 disabled=False, 
#                                 description=record_name)
#             widgets[k].observe(self.update)

#         display(VBox(list(widgets.values())))

#         return widgets

#     @classmethod
#     def _process_iterations(cls,
#                             widgets: dict[str],
#                             data: DataManager, 
#                             capture_record_name: str, 
#                             sweep_record_names: list[str]):
#         """
#         Reduce the data along the iteration axis according to how the user
#         wants it (as determined by their entries into the slider widgets)
#         """
#         # Create a list that we can pass to `process_data` so that the data gets reduced properly
#         from acadia.processing import process_data
#         capture_length = data[capture_record_name].shape[0]
#         dimensions = [(data[r].records(), None) for r in sweep_record_names] + [(capture_length, None)]

#         # Update widgets and process data according to whether we want the mean or a single iteration
#         if widgets["iteration_selector"].value == "Mean":
#             widgets["iteration_slider"].disabled = True

#             # Extract data from the records but compute the mean of all the iterations when doing so
#             data,_ = process_data(data[capture_record_name], [(-1, np.mean)] + dimensions)
#         else:
#             widgets["iteration_slider"].disabled = False

#             # Extract data from only a particular iteration
#             data,_ = process_data(data[capture_record_name], [(-1, widgets["iteration_slider"].value)] + dimensions)
#             widgets["iteration_slider"].max = data.shape[0]-1

#         return data
    
#     def _get_time_axis(self, 
#                        data: DataManager, 
#                        capture_record_name: str) -> np.ndarray:
#         """
#         Get an array of time points for the samples in the traces
#         """
#         capture_length = data[capture_record_name].shape[0]
#         if "capture_time" in data[capture_record_name].metadata():
#             capture_length_time = data[capture_record_name].metadata()["capture_time"]
#             return np.arange(0, capture_length_time, capture_length_time / capture_length)
#         return np.arange(0, capture_length)


#     def _update_plot(self, 
#                      plot_retval, 
#                      traces: np.ndarray, 
#                      time_axis: np.ndarray, 
#                      sweep_axes: list[np.ndarray]):
#         """
#         Update the view of the data, given the trace data and the corresponding
#         time axis.
#         """
#         fig,ax = plot_retval
        
#         # Determine the sweep point that the user has chosen to show
#         sweep_point = tuple(a.index(s.value) for a,s in zip(sweep_axes, self._slid))

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
        

        


        
