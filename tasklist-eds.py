# -*- coding: utf-8 -*-

# Copyright 2014 Alban Browaeys <prahal@yahoo.com>
# License: same as zim (gpl)
#
# Based on tasklist.py with Author:
#    Copyright 2009-2012 Jaap Karssenberg <jaap.karssenberg@gmail.com>
#
# Usage: copy tasklist-eds.py to directory zim/plugins/
# sudo cp tasklist-eds.py "$(dirname $(python -c 'import zim;print zim.__file__'))/plugins"

from __future__ import with_statement

import gtk
import pango
import logging
import re


import zim.datetimetz as datetime
from zim.utils import natural_sorted
from zim.parsing import parse_date
from zim.plugins import PluginClass, extends, ObjectExtension, WindowExtension
from zim.actions import action
from zim.notebook import Path
from zim.gui.widgets import ui_environment, \
	Dialog, MessageDialog, \
	InputEntry, Button, IconButton, MenuButton, \
	BrowserTreeView, SingleClickTreeView, ScrolledWindow, HPaned, \
	encode_markup_text, decode_markup_text
from zim.gui.clipboard import Clipboard
from zim.signals import DelayedCallback, SIGNAL_AFTER
from zim.formats import get_format, \
	UNCHECKED_BOX, CHECKED_BOX, XCHECKED_BOX, BULLET, \
	PARAGRAPH, NUMBEREDLIST, BULLETLIST, LISTITEM, STRIKE, \
	Visitor, VisitorSkip
from zim.config import StringAllowEmpty

from zim.plugins.calendar import daterange_from_path

logger = logging.getLogger('zim.plugins.tasklist-eds')


_tag_re = re.compile(r'(?<!\S)@(\w+)\b', re.U)
_date_re = re.compile(r'\s*\[d:(.+)\]')


_NO_DATE = '9999' # Constant for empty due date - value chosen for sorting properties
_NO_TAGS = '__no_tags__' # Constant that serves as the "no tags" tag - _must_ be lower case

# FUTURE: add an interface for this plugin in the WWW frontend

# TODO allow more complex queries for filter, in particular (NOT tag AND tag)
# TODO: think about what "actionable" means
#       - no open dependencies
#       - no defer date in the future
#       - no child item ?? -- hide in flat list ?
#       - no @waiting ?? -> use defer date for this use case


# TODO
# commandline option
# - open dialog
# - output to stdout with configurable format
# - force update, intialization


class TaskListPlugin(PluginClass):

	plugin_info = {
		'name': _('Task List EDS'), # T: plugin name
		'description': _('''\
This plugin adds a dialog showing all pending tasks in
evolution data server.
'''), # T: plugin description
		'author': 'Alban Browaeys <prahal@yahoo.com>',
		'help': 'Plugins:Task List EDS'
	}

	def extend(self, obj):
		name = obj.__class__.__name__
		if name == 'MainWindow':
			index = obj.ui.notebook.index # XXX
			i_ext = self.get_extension(IndexExtension, index=index)
			mw_ext = MainWindowExtension(self, obj, i_ext)
			self.extensions.add(mw_ext)
		else:
			PluginClass.extend(self, obj)


@extends('Index')
class IndexExtension(ObjectExtension):
	def __init__(self, plugin, index):
		ObjectExtension.__init__(self, plugin, index)
		self.plugin = plugin
		self.index = index

	def list_tasks(self):
		'''List tasks
		@returns: a list of tasks at this level as an array
		'''

                import dbus
                bus = dbus.SessionBus()
                proxy_obj = bus.get_object("org.gnome.Shell.TaskListServer", "/org/gnome/Shell/TaskListServer")
                interf_obj = dbus.Interface(proxy_obj, 'org.gnome.Shell.TaskListServer')
                reply = interf_obj.GetTasks(True)
                keys = ['uid', 'summary', 'description', 'start', 'end', 'due']
                for row in reply:
                    r =  dict(zip(keys, row))
                    r['prio'] = 0
                    yield r



@extends('MainWindow')
class MainWindowExtension(WindowExtension):

	uimanager_xml = '''
		<ui>
			<menubar name='menubar'>
				<menu action='view_menu'>
					<placeholder name="plugin_items">
						<menuitem action="show_eds_task_list" />
					</placeholder>
				</menu>
			</menubar>
			<toolbar name='toolbar'>
				<placeholder name='tools'>
					<toolitem action='show_eds_task_list'/>
				</placeholder>
			</toolbar>
		</ui>
	'''

	def __init__(self, plugin, window, index_ext):
		WindowExtension.__init__(self, plugin, window)
		self.index_ext = index_ext

	@action(_('Task List EDS'), stock='zim-task-list', readonly=True) # T: menu item
	def show_eds_task_list(self):
		dialog = TaskListDialog.unique(self, self.window, self.index_ext)
		dialog.present()


class TaskListDialog(Dialog):

	def __init__(self, window, index_ext):
		Dialog.__init__(self, window, _('Task List EDS'), # T: dialog title
			buttons=gtk.BUTTONS_CLOSE, help=':Plugins:Task List EDS',
			defaultwindowsize=(550, 400) )
		self.index_ext = index_ext

		hbox = gtk.HBox(spacing=5)
		self.vbox.pack_start(hbox, False)
		self.hpane = HPaned()
		self.uistate.setdefault('hpane_pos', 75)
		self.hpane.set_position(self.uistate['hpane_pos'])
		self.vbox.add(self.hpane)

		# Task list
		opener = window.get_resource_opener()
		self.task_list = TaskListTreeView(
			self.index_ext, opener
		)
		self.task_list.set_headers_visible(True) # Fix for maemo
		self.hpane.add2(ScrolledWindow(self.task_list))

		# Tag list
		self.tag_list = TagListTreeView(self.index_ext, self.task_list)
		self.hpane.add1(ScrolledWindow(self.tag_list))

		# Filter input
		hbox.pack_start(gtk.Label(_('Filter')+': '), False) # T: Input label
		filter_entry = InputEntry()
		filter_entry.set_icon_to_clear()
		hbox.pack_start(filter_entry, False)
		filter_cb = DelayedCallback(500,
			lambda o: self.task_list.set_filter(filter_entry.get_text()))
		filter_entry.connect('changed', filter_cb)

		# Dropdown with options - TODO
		#~ menu = gtk.Menu()
		#~ showtree = gtk.CheckMenuItem(_('Show _Tree')) # T: menu item in options menu
		#~ menu.append(showtree)
		#~ menu.append(gtk.SeparatorMenuItem())
		#~ showall = gtk.RadioMenuItem(None, _('Show _All Items')) # T: menu item in options menu
		#~ showopen = gtk.RadioMenuItem(showall, _('Show _Open Items')) # T: menu item in options menu
		#~ menu.append(showall)
		#~ menu.append(showopen)
		#~ menubutton = MenuButton(_('_Options'), menu) # T: Button label
		#~ hbox.pack_start(menubutton, False)

		# Statistics label
		self.statistics_label = gtk.Label()
		hbox.pack_end(self.statistics_label, False)


		def set_statistics():
			total, stats = self.task_list.get_statistics()
			text = ngettext('%i open item', '%i open items', total) % total
				# T: Label for statistics in Task List, %i is the number of tasks
			text += ' (' + '/'.join(map(str, stats)) + ')'
			self.statistics_label.set_text(text)

		set_statistics()

		def on_tasklist_changed(o):
			self.task_list.refresh()
			self.tag_list.refresh(self.task_list)
			set_statistics()

		callback = DelayedCallback(10, on_tasklist_changed)
			# Don't really care about the delay, but want to
			# make it less blocking - should be async preferably
			# now it is at least on idle
		self.connectto(index_ext, 'tasklist-changed', callback)

	def do_response(self, response):
		self.uistate['hpane_pos'] = self.hpane.get_position()
		Dialog.do_response(self, response)


class TagListTreeView(SingleClickTreeView):
	'''TreeView with a single column 'Tags' which shows all tags available
	in a TaskListTreeView. Selecting a tag will filter the task list to
	only show tasks with that tag.
	'''

	_type_separator = 0
	_type_label = 1
	_type_tag = 2
	_type_untagged = 3

	def __init__(self, index_ext, task_list):
		model = gtk.ListStore(str, int, int, int) # tag name, number of tasks, type, weight
		SingleClickTreeView.__init__(self, model)
		self.get_selection().set_mode(gtk.SELECTION_MULTIPLE)
		self.index_ext = index_ext
		self.task_list = task_list

		column = gtk.TreeViewColumn(_('Tags'))
			# T: Column header for tag list in Task List dialog
		self.append_column(column)

		cr1 = gtk.CellRendererText()
		cr1.set_property('ellipsize', pango.ELLIPSIZE_END)
		column.pack_start(cr1, True)
		column.set_attributes(cr1, text=0, weight=3) # tag name, weight

		cr2 = self.get_cell_renderer_number_of_items()
		column.pack_start(cr2, False)
		column.set_attributes(cr2, text=1) # number of tasks

		self.set_row_separator_func(lambda m, i: m[i][2] == self._type_separator)

		self._block_selection_change = False

		self.refresh(task_list)

	def _get_selected(self):
		selection = self.get_selection()
		if selection:
			model, paths = selection.get_selected_rows()
			if not paths or (0,) in paths:
				return []
			else:
				return [model[path] for path in paths]
		else:
			return []

	def refresh(self, task_list):
		self._block_selection_change = True
		selected = [(row[0], row[2]) for row in self._get_selected()] # remember name and type

		# Rebuild model
		model = self.get_model()
		if model is None: return
		model.clear()

		n_all = self.task_list.get_n_tasks()
		model.append((_('All Tasks'), n_all, self._type_label, pango.WEIGHT_BOLD)) # T: "tag" for showing all tasks

		# Restore selection
		def reselect(model, path, iter):
			row = model[path]
			name_type = (row[0], row[2])
			if name_type in selected:
				self.get_selection().select_iter(iter)

		if selected:
			model.foreach(reselect)
		self._block_selection_change = False


HIGH_COLOR = '#EF5151' # red (derived from Tango style guide - #EF2929)
MEDIUM_COLOR = '#FCB956' # orange ("idem" - #FCAF3E)
ALERT_COLOR = '#FCEB65' # yellow ("idem" - #FCE94F)
# FIXME: should these be configurable ?


class TaskListTreeView(BrowserTreeView):

	VIS_COL = 0 # visible
	PRIO_COL = 1
	TASK_COL = 2
	DATE_COL = 3
	TASKID_COL = 4
	DESCR_COL = 4

	def __init__(self, index_ext, opener):
		self.real_model = gtk.TreeStore(bool, int, str, str, str, str)
			# VIS_COL, PRIO_COL, TASK_COL, DATE_COL, TASKID_COL, DESCR_COL
		model = self.real_model.filter_new()
		model.set_visible_column(self.VIS_COL)
		model = gtk.TreeModelSort(model)
		model.set_sort_column_id(self.PRIO_COL, gtk.SORT_DESCENDING)
		BrowserTreeView.__init__(self, model)

		self.index_ext = index_ext
		self.opener = opener
		self.filter = None

		# Add some rendering for the Prio column
		def render_prio(col, cell, model, i):
			prio = model.get_value(i, self.PRIO_COL)
			cell.set_property('text', str(prio))
			if prio >= 3: color = HIGH_COLOR
			elif prio == 2: color = MEDIUM_COLOR
			elif prio == 1: color = ALERT_COLOR
			else: color = None
			cell.set_property('cell-background', color)

		cell_renderer = gtk.CellRendererText()
		#~ column = gtk.TreeViewColumn(_('Prio'), cell_renderer)
			# T: Column header Task List dialog
		column = gtk.TreeViewColumn(' ! ', cell_renderer)
		column.set_cell_data_func(cell_renderer, render_prio)
		column.set_sort_column_id(self.PRIO_COL)
		self.append_column(column)

		# Rendering for task summary column
		cell_renderer = gtk.CellRendererText()
		cell_renderer.set_property('ellipsize', pango.ELLIPSIZE_END)
		column = gtk.TreeViewColumn(_('Task'), cell_renderer, markup=self.TASK_COL)
				# T: Column header Task List dialog
		column.set_resizable(True)
		column.set_sort_column_id(self.TASK_COL)
		column.set_expand(True)
		if ui_environment['platform'] == 'maemo':
			column.set_min_width(250) # don't let this column get too small
		else:
			column.set_min_width(300) # don't let this column get too small
		self.append_column(column)
		self.set_expander_column(column)

		if gtk.gtk_version >= (2, 12, 0):
			self.set_tooltip_column(self.TASK_COL)

		day_of_week = datetime.date.today().isoweekday()
                delta1, delta2 = 1, 2

		today    = str( datetime.date.today() )
		tomorrow = str( datetime.date.today() + datetime.timedelta(days=delta1))
		dayafter = str( datetime.date.today() + datetime.timedelta(days=delta2))
		def render_date(col, cell, model, i):
			date = model.get_value(i, self.DATE_COL)
			if date == _NO_DATE:
				cell.set_property('text', '')
			else:
				cell.set_property('text', date)
				# TODO allow strftime here

			if date <= today: color = HIGH_COLOR
			elif date <= tomorrow: color = MEDIUM_COLOR
			elif date <= dayafter: color = ALERT_COLOR
				# "<=" because tomorrow and/or dayafter can be after the weekend
			else: color = None
			cell.set_property('cell-background', color)

		cell_renderer = gtk.CellRendererText()
		column = gtk.TreeViewColumn(_('Date'), cell_renderer)
			# T: Column header Task List dialog
		column.set_cell_data_func(cell_renderer, render_date)
		column.set_sort_column_id(self.DATE_COL)
		self.append_column(column)

		# Finalize
		self.refresh()

	def refresh(self):
		'''Refresh the model based on index data'''
		# Update data
		self._clear()
		self._append_tasks(None, None, {})

		# Set view
		self._eval_filter() # keep current selection
		self.expand_all()

	def _clear(self):
		self.real_model.clear() # flush

	def _append_tasks(self, task, iter, path_cache):
		for row in self.index_ext.list_tasks():
			# Format summary
			task = _date_re.sub('', row['summary'], count=1)
			task = re.sub('\s*!+\s*', ' ', task) # get rid of exclamation marks
			task = encode_markup_text(task)
                        task = r'<span color="darkgrey">%s</span>' % task

			# Insert all columns
			modelrow = [False, row['prio'], task, row['due'], row['uid'], row['description']]
				# VIS_COL, PRIO_COL, TASK_COL, DATE_COL, TASKID_COL, DESCR_COL
			modelrow[0] = self._filter_item(modelrow)
			myiter = self.real_model.append(iter, modelrow)

	def set_filter(self, string):
		# TODO allow more complex queries here - same parse as for search
		if string:
			inverse = False
			if string.lower().startswith('not '):
				# Quick HACK to support e.g. "not @waiting"
				inverse = True
				string = string[4:]
			self.filter = (inverse, string.strip().lower())
		else:
			self.filter = None
		self._eval_filter()

	def get_n_tasks(self):
		'''Get the number of tasks in the list
		@returns: total number
		'''
		counter = [0]
		def count(model, path, iter):
                        counter[0] += 1
		self.real_model.foreach(count)
		return counter[0]

	def get_statistics(self):
		statsbyprio = {}

		def count(model, path, iter):
			# only count open items
			row = model[iter]
                        prio = row[self.PRIO_COL]
                        statsbyprio.setdefault(prio, 0)
                        statsbyprio[prio] += 1

		self.real_model.foreach(count)

		if statsbyprio:
			total = reduce(int.__add__, statsbyprio.values())
			highest = max([0] + statsbyprio.keys())
			stats = [statsbyprio.get(k, 0) for k in range(highest+1)]
			stats.reverse() # highest first
			return total, stats
		else:
			return 0, []

	def _eval_filter(self):
		logger.debug('Filtering with filter: %s', self.filter)

		def filter(model, path, iter):
			visible = self._filter_item(model[iter])
			model[iter][self.VIS_COL] = visible
			if visible:
				parent = model.iter_parent(iter)
				while parent:
					model[parent][self.VIS_COL] = visible
					parent = model.iter_parent(parent)

		self.real_model.foreach(filter)
		self.expand_all()

	def _filter_item(self, modelrow):
		# This method filters case insensitive because both filters and
		# text are first converted to lower case text.
		visible = True

		summary = modelrow[self.TASK_COL].decode('utf-8').lower()

		if visible and self.filter:
			# And finally the filter string should match
			# FIXME: we are matching against markup text here - may fail for some cases
			inverse, string = self.filter
			match = string in summary
			if (not inverse and not match) or (inverse and match):
				visible = False

		return visible


	def _get_raw_text(self, task):
		return task[self.DESCR_COL]

	def do_initialize_popup(self, menu):
		item = gtk.ImageMenuItem('gtk-copy')
		item.connect('activate', self.copy_to_clipboard)
		menu.append(item)
		self.populate_popup_expand_collapse(menu)

	def copy_to_clipboard(self, *a):
		'''Exports currently visible elements from the tasks list'''
		logger.debug('Exporting to clipboard current view of task list.')
		text = self.get_visible_data_as_csv()
		Clipboard.set_text(text)
			# TODO set as object that knows how to format as text / html / ..
			# unify with export hooks

	def get_visible_data_as_csv(self):
		text = ""
		for indent, prio, desc, date, page in self.get_visible_data():
			prio = str(prio)
			desc = decode_markup_text(desc)
			desc = '"' + desc.replace('"', '""') + '"'
			text += ",".join((prio, desc, date, page)) + "\n"
		return text

	def get_visible_data_as_html(self):
		html = '''\
<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
	<head>
		<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
		<title>Task List - Zim</title>
		<meta name='Generator' content='Zim [%% zim.version %%]'>
		<style type='text/css'>
			table.tasklist {
				border-width: 1px;
				border-spacing: 2px;
				border-style: solid;
				border-color: gray;
				border-collapse: collapse;
			}
			table.tasklist th {
				border-width: 1px;
				padding: 1px;
				border-style: solid;
				border-color: gray;
			}
			table.tasklist td {
				border-width: 1px;
				padding: 1px;
				border-style: solid;
				border-color: gray;
			}
			.high {background-color: %s}
			.medium {background-color: %s}
			.alert {background-color: %s}
		</style>
	</head>
	<body>

<h1>Task List - Zim</h1>

<table class="tasklist">
<tr><th>Prio</th><th>Task</th><th>Date</th><th>Page</th></tr>
''' % (HIGH_COLOR, MEDIUM_COLOR, ALERT_COLOR)

		today    = str( datetime.date.today() )
		tomorrow = str( datetime.date.today() + datetime.timedelta(days=1))
		dayafter = str( datetime.date.today() + datetime.timedelta(days=2))
		for indent, prio, summary, date in self.get_visible_data():
			if prio >= 3: prio = '<td class="high">%s</td>' % prio
			elif prio == 2: prio = '<td class="medium">%s</td>' % prio
			elif prio == 1: prio = '<td class="alert">%s</td>' % prio
			else: prio = '<td>%s</td>' % prio

			if date and date <= today: date = '<td class="high">%s</td>' % date
			elif date == tomorrow: date = '<td class="medium">%s</td>' % date
			elif date == dayafter: date = '<td class="alert">%s</td>' % date
			else: date = '<td>%s</td>' % date

			summary = '<td>%s%s</td>' % ('&nbsp;' * (4 * indent), summary)
			page = '<td>%s</td>' % page

			html += '<tr>' + prio + summary + date + page + '</tr>\n'

		html += '''\
</table>

	</body>

</html>
'''
		return html

	def get_visible_data(self):
		rows = []

		def collect(model, path, iter):
			indent = len(path) - 1 # path is tuple with indexes

			row = model[iter]
			prio = row[self.PRIO_COL]
			desc = row[self.TASK_COL].decode('utf-8')
			date = row[self.DATE_COL]

			if date == _NO_DATE:
				date = ''

			rows.append((indent, prio, desc, date))

		model = self.get_model()
		model.foreach(collect)

		return rows

# Need to register classes defining gobject signals
#~ gobject.type_register(TaskListTreeView)
# NOTE: enabling this line causes this treeview to have wrong theming under default ubuntu them !???
