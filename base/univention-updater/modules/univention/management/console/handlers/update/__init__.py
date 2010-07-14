#!/usr/bin/python2.4
# -*- coding: utf-8 -*-
#
# Univention Management Console
#  module: manage updates
#
# Copyright 2008-2010 Univention GmbH
#
# http://www.univention.de/
#
# All rights reserved.
#
# The source code of this program is made available
# under the terms of the GNU Affero General Public License version 3
# (GNU AGPL V3) as published by the Free Software Foundation.
#
# Binary versions of this program provided by Univention to you as
# well as other copyrighted, protected or trademarked materials like
# Logos, graphics, fonts, specific documentations and configurations,
# cryptographic keys etc. are subject to a license agreement between
# you and Univention and not subject to the GNU AGPL V3.
#
# In the case you use this program under the terms of the GNU AGPL V3,
# the program is provided in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License with the Debian GNU/Linux or Univention distribution in file
# /usr/share/common-licenses/AGPL-3; if not, see
# <http://www.gnu.org/licenses/>.

import univention.management.console as umc
import univention.management.console.categories as umcc
import univention.management.console.protocol as umcp
import univention.management.console.handlers as umch
import univention.management.console.dialog as umcd
import univention.management.console.tools as umct

import univention.debug as ud

import univention.config_registry

from univention.updater import UniventionUpdater
from json import JsonReader, JsonWriter

import os, copy
import subprocess, string, time
import socket, re
import traceback

_ = umc.Translation('univention.management.console.handlers.update').translate

icon = 'update/module'
short_description = _('Online updates')
long_description = _('Manage system updates')
categories = ['all', 'system']

UCR_ALLOWED_CHARACTERS = '^[^#:@]+$'
FN_LIST_INSTALL_COMPONENT_LOG = [ '/var/log/univention/actualise.log' ]
FN_LIST_SECURITY_UPDATE_LOG = [ '/var/log/univention/security-updates.log' ]
FN_LIST_RELEASE_UPDATE_LOG = [ '/var/log/univention/updater.log' ]
FN_LIST_DIST_UPGRADE_LOG = [ '/var/log/univention/updater.log' ]

command_description = {
	'update/overview': umch.command(
		short_description = _('Updates'),
		long_description = _('Updates'),
		method = 'overview',
		values = { },
		startup = True,
		priority = 100,
		caching = False
	),
	'update/settings': umch.command(
		short_description = _('Settings'),
		long_description = _('Settings'),
		method = 'settings',
		values = { },
		startup = True,
		priority = 80,
		caching = False
	),
	'update/release_settings': umch.command(
		short_description = _('Release update settings'),
		long_description = _('Release update settings'),
		method = 'release_settings',
		values = {
			'repository_server': umc.String(_('Repository server')),
			'repository_prefix': umc.String(_('Repository prefix'), required = False),
			'use_hotfixes': umc.Boolean( _( 'Use hotfix repositories' ), required = False ),
			'use_maintained': umc.Boolean( _( 'Use maintained repositories' ), required = False ),
			'use_unmaintained': umc.Boolean( _( 'Use unmaintained repositories' ), required = False ),
			},
		caching = False
	),
	'update/components_update': umch.command(
		short_description = _('Check for updates'),
		method = 'components_update',
		values = { },
	),
	'update/components_settings': umch.command(
		short_description = _('Component settings'),
		method = 'components_settings',
		values = {
			'component_activated': umc.Boolean(_('Enabled'), required = False),
			'component_server': umc.String(_('Server'), required = False),
			'component_prefix': umc.String(_('Prefix'), required = False),
			'component_name': umc.String(_('Name')),
			'component_description': umc.String(_('Description'), required = False),
			'component_unmaintained': umc.String(_('Unmaintained'), required = False),
			'component_username': umc.String(_('Username'), required = False),
			'component_password': umc.String(_('Password'), required = False, regex = UCR_ALLOWED_CHARACTERS),
			'use_maintained': umc.Boolean( _( 'Use maintained repositories' ), required = False ),
			'use_unmaintained': umc.Boolean( _( 'Use unmaintained repositories' ), required = False ),
		},
	),
	'update/install_release_updates': umch.command(
		short_description = _('Installs a release update'),
		method = 'install_release_updates',
		values = { },
	),
	'update/install_security_updates': umch.command(
		short_description = _('Installs security updates'),
		method = 'install_security_updates',
		values = { },
	),
	'update/tail_logfile': umch.command(
		short_description = _('Get tail of logfile'),
		method = 'tail_logfile',
		values = {
			'filename': umc.String( _( 'Name of log file' ), required = False ),
		},
	),
	'update/tail_logfile_dialog': umch.command(
		short_description = _('Get dialog with AJAX logfile output'),
		method = 'tail_logfile_dialog',
		values = {
			'filename': umc.String( _( 'Name of log file' ), required = False ),
		},
	),
	'update/update_warning': umch.command(
		short_description = _('View an update warning'),
		method = 'update_warning',
		values = {
		},
	),

}


class VersionSelection( umc.StaticSelection ):
	def __init__( self, custom_choices=None ):
		umc.StaticSelection.__init__( self, _( 'Update system up to release version' ) )
		self.custom_choices = custom_choices

	def choices( self ):
		if not self.custom_choices:
			return [ [ 'none', 'none' ] ]
		return self.custom_choices
umcd.copy( umc.StaticSelection, VersionSelection )


class handler(umch.simpleHandler):

	def __init__(self):
		_d = ud.function('update.handler.__init__')

		global command_description

		umch.simpleHandler.__init__(self, command_description)

		self.updater = UniventionUpdater()

		self.next_release_update_checked = False
		self.next_release_update = None
		self.next_securtiy_update = None

		self.ucr_reinit = False

		self.tail_fn2fd = {}

		self.command_dist_upgrade = self.updater.configRegistry.get('update/commands/distupgrade', 'apt-get -o DPkg::Options::=--force-confold -o DPkg::Options::=--force-overwrite -o DPkg::Options::=--force-overwrite-dir -y --force-yes -u dist-upgrade')


	def overview(self, object):
		_d = ud.function('update.handler.overview')
		self.finished(object.id(), None)

	def settings(self, object):
		_d = ud.function('update.handler.settings')
		self.finished(object.id(), None)

	def release_settings(self, object):
		_d = ud.function('update.handler.release_settings')

		reset = False
		set_variables = []

		if object.options.has_key('repository_server') and self.updater.repository_server != object.options[ 'repository_server' ]:
			ud.debug(ud.ADMIN, ud.INFO, 'Updater: release_settings: repository_server was set to: %s' % object.options['repository_server'])
			set_variables.append( 'repository/online/server=%s' % object.options['repository_server'] )
			self.updater.repository_server=object.options['repository_server']
			reset = True
		if object.options.has_key('repository_prefix'):
			if object.options['repository_prefix'] and object.options['repository_prefix'] != self.updater.repository_prefix:
				ud.debug(ud.ADMIN, ud.INFO, 'Updater: release_settings: repository_prefix was set to: %s' % object.options['repository_prefix'])
				set_variables.append( 'repository/online/prefix=%s' % object.options['repository_prefix'] )
				self.updater.repository_prefix=object.options['repository_prefix']
			else:
				univention.config_registry.handler_unset( [ 'repository/online/prefix' ] )
			reset = True
		ud.debug( ud.ADMIN, ud.INFO, 'Updater: release_settings: options: %s' % str( object.options ) )
		if object.options.has_key( 'use_hotfixes' ):
			ud.debug( ud.ADMIN, ud.INFO, 'Updater: release_settings: use_hotfixes was set to: %s' % object.options[ 'use_hotfixes' ] )
			if object.options[ 'use_hotfixes' ] and not self.updater.hotfixes:
				set_variables.append( 'repository/online/hotfixes=yes' )
			elif not object.options[ 'use_hotfixes' ] and self.updater.hotfixes:
				set_variables.append( 'repository/online/hotfixes=no' )
			self.updater.hotfixes = object.options[ 'use_hotfixes' ]
			reset = True

		if object.options.has_key( 'use_maintained' ):
			ud.debug( ud.ADMIN, ud.INFO, 'Updater: release_settings: use_maintained was set to: %s' % object.options[ 'use_maintained' ] )
			if object.options[ 'use_maintained' ]:
				if not 'maintained' in self.updater.parts:
					self.updater.parts.append( 'maintained' )
					set_variables.append( 'repository/online/maintained=yes' )
			else:
				if 'maintained' in self.updater.parts:
					self.updater.parts.remove( 'maintained' )
					set_variables.append( 'repository/online/maintained=no' )
			reset = True

		if object.options.has_key( 'use_unmaintained' ):
			ud.debug( ud.ADMIN, ud.INFO, 'Updater: release_settings: use_unmaintained was set to: %s' % object.options[ 'use_unmaintained' ] )
			if object.options[ 'use_unmaintained' ]:
				if not 'unmaintained' in self.updater.parts:
					self.updater.parts.append( 'unmaintained' )
					set_variables.append( 'repository/online/unmaintained=yes' )
			else:
				if 'unmaintained' in self.updater.parts:
					self.updater.parts.remove( 'unmaintained' )
					set_variables.append( 'repository/online/unmaintained=no' )
			reset = True

		if set_variables:
			univention.config_registry.handler_set( set_variables )

		if reset:
			self.next_release_update_checked = False

		self.finished(object.id(), None)



	def _reinit(self):
		try:
			self.updater.ucr_reinit()
		except (socket.error, socket.gaierror), e:
			import traceback
			ud.debug(ud.ADMIN, ud.ERROR, 'updater: socket.gaierror: %s' % traceback.format_exc().replace('%','§'))
		except Exception, e:
			ud.debug(ud.ADMIN, ud.ERROR, 'updater: %s' % (traceback.format_exc().replace('%','§')))


	def components_update(self, object):
		_d = ud.function('update.handler.components_update')

		status = object.options.get('status', None)
		if status == 'check':
			p1 = subprocess.Popen(['univention-config-registry commit /etc/apt/sources.list.d/20_ucs-online-component.list; LC_ALL=C apt-get update >/dev/null; LC_ALL=C apt-get -u dist-upgrade -s'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
			(stdout,stderr) = p1.communicate()
			ud.debug(ud.ADMIN, ud.PROCESS, 'check for updates with "dist-upgrade -s", the returncode is %d' % p1.returncode)
			ud.debug(ud.ADMIN, ud.PROCESS, 'stderr=%s' % stderr)
			ud.debug(ud.ADMIN, ud.INFO, 'stdout=%s' % stdout)

			new_packages = []
			upgraded_packages = []
			for line in stdout.split('\n'):
				if line.startswith('Inst '):
					line_split = line.split(' ')
					# upgrade:
					#   Inst univention-updater [3.1.1-5] (3.1.1-6.408.200810311159 192.168.0.10)
					# inst:
					#   Inst mc (1:4.6.1-6.12.200710211124 oxae-update.open-xchange.com)
					if len(line_split) > 3:
						if line_split[2].startswith('[') and line_split[2].endswith(']'):
							ud.debug(ud.ADMIN, ud.PROCESS, 'Added %s to the list of upgraded packages' % line_split[1])
							upgraded_packages.append((line_split[1], line_split[2].replace('[','').replace(']',''), line_split[3].replace('(','')))
						else:
							ud.debug(ud.ADMIN, ud.PROCESS, 'Added %s to the list of new packages' % line_split[1])
							new_packages.append((line_split[1], line_split[2].replace('(','')))
					else:
						ud.debug(ud.ADMIN, ud.WARN, 'unable to parse the update line: %s' % line)
						continue

			update_text = ''
			if len(upgraded_packages) > 0:
				update_text += '<h2>' +_('The following packages will be upgraded:') + '</h2>'
				update_text += '<body>'
				for p in upgraded_packages:
					update_text += '&nbsp;&nbsp; %s %s' % (p[0],p[2])
					update_text += '<br>'
				update_text += '</body>'

			if len(new_packages) > 0:
				update_text += '<h2>' + _('The following NEW packages will be installed:') + '</h2>'
				update_text += '<body>'
				for p in new_packages:
					update_text += '&nbsp;&nbsp; %s %s' % (p[0],p[1])
					update_text += '<br>'
				update_text += '</body>'

			self.finished(object.id(), {'text': update_text})

		elif status == 'warning':
			self.finished(object.id(), None)

		elif status == 'execute':
			cmd = '''echo "Starting dist-upgrade at $(date)" >> %(logfile)s;
			DEBIAN_FRONTEND=noninteractive
			%(cmd)s >> %(logfile)s 2>&1 ;
			if [ $? = 0 ] ; then
				echo >> %(logfile)s ;
				echo "The update has been finished successfully at $(date)."  >> %(logfile)s ;
		    else
				echo >> %(logfile)s ;
				echo "An error occured during update. Please check the logfiles."  >> %(logfile)s ;
				date >> %(logfile)s ;
		    fi
			''' % { 'cmd': self.command_dist_upgrade, 'logfile': FN_LIST_DIST_UPGRADE_LOG }
			(returncode, returnstring) = self.__create_at_job(cmd)
			ud.debug(ud.ADMIN, ud.PROCESS, 'Created the at job: apt-get dist-upgrade' )
			self.finished(object.id(), None)


	def components_settings(self, object):
		_d = ud.function('update.handler.components_settings')

		component_activated = object.options.get('component_activated', '')
		component_server = object.options.get('component_server', '')
		component_prefix = object.options.get('component_prefix', '')
		component_name = object.options.get('component_name', '')
		component_description = object.options.get('component_description', '')
		component_unmaintained = object.options.get('component_unmaintained', '')
		component_username = object.options.get('component_username', '')
		component_password = object.options.get('component_password', '')
		component_use_maintained = object.options.get('use_maintained', '')
		component_use_unmaintained = object.options.get('use_unmaintained', '')

		ud.debug(ud.ADMIN, ud.INFO, 'Component settings for %s' % component_name)
		if component_name:
			res = []
			if component_activated:
				res.append('repository/online/component/%s=enabled' % component_name)
			else:
				res.append('repository/online/component/%s=disabled' % component_name)
			if component_description:
				res.append('repository/online/component/%s/description=%s' % (component_name,component_description))
			if component_server:
				res.append('repository/online/component/%s/server=%s' % (component_name,component_server))
			if component_prefix:
				res.append('repository/online/component/%s/prefix=%s' % (component_name,component_prefix))
			if component_username:
				res.append('repository/online/component/%s/username=%s' % (component_name,component_username))
			if component_password:
				res.append('repository/online/component/%s/password=%s' % (component_name,component_password))
			parts = []
			if component_use_maintained:
				parts.append('maintained')
			if component_use_unmaintained:
				parts.append('unmaintained')
			res.append('repository/online/component/%s/parts=%s' % (component_name, ','.join(parts)))

			ud.debug(ud.ADMIN, ud.INFO, 'Set the following component settings: %s' % res)
			univention.config_registry.handler_set(res)
			ud.debug(ud.ADMIN, ud.INFO, 'And reinit the updater modul')
			self.updater.ucr_reinit()

		self.finished(object.id(), None)

	def update_warning(self, object):
		_d = ud.function('update.handler.release_update_warning')
		self.finished(object.id(), None)

	def install_release_updates(self, object):
		_d = ud.function('update.handler.install_release_updates')

		updateto = object.options.get('updateto',[None])[0]
		ud.debug(ud.ADMIN, ud.PROCESS, 'install_release_updates: updateto=%s' % updateto )
		if updateto:
			(returncode, returnstring) = self.__create_at_job('univention-updater net --updateto %s' % updateto)
			ud.debug(ud.ADMIN, ud.PROCESS, 'Created the at job: univention-updater net --updateto %s' % updateto)
		elif self.updater.configRegistry.get('update/umc/nextversion', 'true').lower() in ['false', 'disabled', '0', 'no']:
			(returncode, returnstring) = self.__create_at_job('univention-updater net')
			ud.debug(ud.ADMIN, ud.PROCESS, 'Created the at job: univention-updater net')
		else:
			(returncode, returnstring) = self.__create_at_job('univention-updater net --updateto %s' % self.next_release_update)
			ud.debug(ud.ADMIN, ud.PROCESS, 'Created the at job: univention-updater net --updateto %s' % self.next_release_update)

		if returncode != 0:
			self.finished(object.id(), None, returnstring, success = False)
		else:
			self.finished(object.id(), None)

	def install_security_updates(self, object):
		_d = ud.function('update.handler.install_security_updates')

		(returncode, returnstring) = self.__create_at_job('univention-security-update net' )
		ud.debug(ud.ADMIN, ud.PROCESS, 'Created the at job: univention-security-update net' )

		if returncode != 0:
			self.finished(object.id(), None, returnstring, success = False)
		else:
			self.finished(object.id(), None)

	def tail_logfile(self, object):
		_d = ud.function('update.handler.tail_logfile')
		self.finished(object.id(), None)

	def tail_logfile_dialog(self, object):
		_d = ud.function('update.handler.tail_logfile_dialog')
		self.finished(object.id(), None)

	#######################
	# The revamp functions
	#######################

	def _web_tail_logfile(self, object, res):
		_d = ud.function('update.handler._web_tail_logfile')

		headline = None
		headline_msg = None
		windowtype = object.options.get('windowtype')
		if windowtype == 'release':
			if not self.__is_updater_running():
				headline = _('Update finished')
				headline_msg = _('The release update has been finished. During update some log messages have been shown in window below. Please check the output for error messages.')
				self._reinit()
		elif windowtype == 'security':
			if not self.__is_security_update_running():
				headline = _('Update finished')
				headline_msg = _('The security update has been finished. During update some log messages have been shown in window below. Please check the output for error messages.')
				self._reinit()
		elif windowtype == 'dist-upgrade':
			if not self.__is_dist_upgrade_running():
				headline = _('Update finished')
				headline_msg = _('The update has been finished. During update some log messages have been shown in window below. Please check the output for error messages.')
				self._reinit()
		else:
			ud.debug(ud.ADMIN, ud.ERROR, 'update.handler._web_tail_logfile: unknown window type: %s' % (windowtype) )

		fdlist = []
		for key in object.options.keys():
			# get all filenames (filename1=... filenameB=...)
			if key.startswith('filename'):
				fn = object.options.get(key)
				# some security checks
				if not fn.startswith('/var/log/univention/'):
					self.finished(object.id(), 'invalid filename%s: access not allowed by UMC module' % fn)
					return
				else:
					# create fd if fd is not present
					try:
						if not fn in self.tail_fn2fd:
							ud.debug(ud.ADMIN, ud.INFO, 'update.handler._web_tail_logfile: opening %s' % fn)
							fd = open(fn,'r+')
							fd.seek(0,2)				 # seek to file end ==> show only new entries
							#fd.seek(-16384,2)			 # seek to 16384 bytes before file end ==> show last 16k of file
							self.tail_fn2fd[fn] = fd
						else:
							fd = self.tail_fn2fd[fn]
						fdlist.append(fd)
					except Exception, e:
						ud.debug(ud.ADMIN, ud.WARN, 'update.handler._web_tail_logfile: cannot open: %s ==> %s' % (fn, str(e)) )

		logdata = ''
		for fd in fdlist:
			curpos = fd.tell()
			fd.seek(0,2)	   # seek to file end
			endpos = fd.tell()
			fd.seek(curpos,0)  # seek back to cur pos
			pendingbytes = endpos - curpos
			logdata += fd.read(pendingbytes)  # get pending data

		data = { 'contentappend': logdata }
		if headline:
			data['tail_headline'] = str(headline)
		if headline_msg:
			data['tail_headlinemsg'] = str(headline_msg)
		try:
			json = JsonWriter()
			content = json.write(data)
		except:
			content = ''
			ud.debug(ud.ADMIN, ud.ERROR, 'update.handler._web_tail_logfile: failed to create JSON: %s' % (traceback.format_exc().replace('%','#')) )

		res.dialog = { 'Content-Type': 'application/json', 'Content': content }
		self.revamped( object.id(), res, rawresult = True )


	def _web_tail_logfile_dialog(self, object, res):
		_d = ud.function('update.handler._web_tail_logfile_dialog')

		windowtype = object.options.get('windowtype','undefined-local')

		# depending on window type set headline, headline message and logfiles
		if windowtype == 'release':
			txt_headline = _('Update progress')
			txt_headline_msg = _('The release update process has been started. During update log messages will be shown in window below. Please wait until the release update has been finished.')
			filenames = FN_LIST_RELEASE_UPDATE_LOG
		elif windowtype == 'security':
			txt_headline = _('Security update progress')
			txt_headline_msg = _('The security update process has been started. During update log messages will be shown in window below. Please wait until the security update has been finished.')
			filenames = FN_LIST_SECURITY_UPDATE_LOG
		elif windowtype == 'dist-upgrade':
			txt_headline = _('Update progress')
			txt_headline_msg = _('The update process has been started. During update log messages will be shown in window below. Please wait until the update has been finished.')
			filenames = FN_LIST_DIST_UPGRADE_LOG
		else:
			ud.debug(ud.ADMIN, ud.ERROR, 'update.handler.__create_tail_window: unknown window type: %s' % (windowtype) )
			txt_headline = 'ERROR'
			txt_headline_msg = 'ERROR MSG'
			filenames = FN_LIST_RELEASE_UPDATE_LOG

		lst = umcd.List()
		lst.add_row( [ umcd.HTML('<h2 id="tail_headline">' + txt_headline + '</h2') ] )
		lst.add_row( [ umcd.HTML( '<div id="tail_headlinemsg">' +  txt_headline_msg + '</div>' ) ] )
		# convert filename list
		opts = { 'windowtype' : windowtype }
		i = 1
		for fn in filenames:
			opts['filename%d' % i] = fn
			i += 1
		# add refresh frame
		lst.add_row( [ umcd.RefreshFrame( self._sessionid, 'update/tail_logfile', opts, attributes = { 'colspan': '3', 'width': '900', 'height': '400' }, refresh_interval=1000) ] )
		# add close button
		cmd = umcp.Command( args = [ 'update/overview' ], opts = { } )
		item_btn = umcd.Button( _('Close'), 'actions/ok', actions = [ umcd.Action( cmd ) ] )
		lst.add_row( [ item_btn ] )
		res.dialog = [ lst ]
		self.revamped(object.id(), res)


	# This revamp function shows the Overview site
	def _web_overview(self, object, res):
		_d = ud.function('update.handler._web_overview')

		#### Important Information

		frame_info = None
		# Is a reboot required?
		if self.updater.configRegistry.get( 'update/reboot/required', 'no' ) == 'yes':
			list_info = umcd.List()
			frame_info = umcd.Frame( [ list_info ], _( 'Important Information' ) )
			list_info.add_row( [ umcd.InfoBox( _( 'The system has been updated to a newer version of UCS. It is suggested that the system should be rebooted after the update. This has not been done yet.' ), columns = 2 ) ] )
			cmd = umcp.Command( args = [ 'reboot/do' ], opts = { 'action' : 'reboot', 'message' : _( 'Rebooting the system after an update' ) } )
			list_info.add_row( [ '', umcd.Button( _( 'Reboot system' ), 'actions/ok', actions = [ umcd.Action( cmd ) ] ) ] )
		#### UCS Releases
		list_config = umcd.List()
		list_release = umcd.List()

		local_repo = self.updater.configRegistry.get( 'local/repository', 'no' ).lower() in ( 'yes', 'true' )

		# ==== UCS RELEASE UPDATES =====
		list_update_release = umcd.List()

		if self.__is_updater_running():
			# release update is running ==> show logfile button
			req = self.__get_logfile_request( { 'windowtype': 'release' } )
			btn_view_log = umcd.Button( _( 'View logfile' ), 'actions/install', actions = [ umcd.Action( req ) ] )
			list_update_release.add_row([ umcd.Text(_('The update is still in progress.')), btn_view_log])

		elif self.__is_security_update_running() or self.__is_dist_upgrade_running():
			# release update button is disabled due to running updates
			txt = umcd.Text( _('The currently installed release version is %s.') % self.updater.get_ucs_version() )
			txt['colspan'] = '2'
			list_update_release.add_row([ txt ])

		else:
			# get all available release updates
			errormsg = None
			try:
				available_release_updates, blocking_component = self.updater.get_all_available_release_updates()
			except (socket.error, socket.gaierror), e:
				ud.debug(ud.ADMIN, ud.ERROR, 'updater: socket.gaierror: %s' % traceback.format_exc().replace('%','§'))
				errormsg = _( 'The connection to the repository server failed: %s. Please check the repository settings and the network connection.' ) % str( e[ 1 ] )
			except Exception, e:
				ud.debug(ud.ADMIN, ud.ERROR, 'updater: %s' % (traceback.format_exc()))
				errormsg = _( 'An error occured during network operation: %s' % traceback.format_exc().replace('%','§'))

			if errormsg:
				list_update_release.add_row([ errormsg ])
			else:
				if not available_release_updates:
					# no release update possible/available
					if blocking_component:
						txt = umcd.Text(_('The currently installed UCR release version is %(version)s. Further release updates are available but the update is blocked by required component "%(component)s".') % { 'version': self.updater.get_ucs_version(), 'component': blocking_component})
					else:
						txt = umcd.Text( _('The currently installed version is %s and there is no update available.') % self.updater.get_ucs_version() )
					txt['colspan'] = '2'
					list_update_release.add_row([ txt ])

				else:
					# release update possible/available
					txt = umcd.Text( _('The currently installed release version is %s and new release updates are available.') % self.updater.get_ucs_version() )
					txt['colspan'] = '2'
					list_update_release.add_row([ txt ])

					choices = []
					for ver in available_release_updates:
						choices.append( (ver, 'UCS %s' % ver) )
					sel_version = umcd.Selection( ( 'updateto', VersionSelection( choices ) ), default = available_release_updates[-1] )
					idlist = [ sel_version.id() ]
					btn_install_release_update = umcd.Button(_('Install release updates'), 'actions/install', actions = [umcd.Action(self.__get_warning_request({'type': 'release', 'updateto':[]}), idlist)])

					list_update_release.add_row([ sel_version, btn_install_release_update ])

		# ==== UCS SECURITY UPDATES =====
		list_update_security = umcd.List()

		if self.__is_security_update_running():
			# security update is running ==> show logfile button
			req = self.__get_logfile_request( { 'windowtype': 'security' } )
			btn_view_log = umcd.Button( _( 'View logfile' ), 'actions/install', actions = [ umcd.Action( req ) ] )
			list_update_security.add_row([ umcd.Text(_('The security update is still in progress.')), btn_view_log])

		elif self.__is_updater_running() or self.__is_dist_upgrade_running():
			# release update button is disabled due to running updates
			txt = umcd.Text( _('The currently installed security update version is %s.') % self.updater.security_patchlevel )
			txt['colspan'] = '2'
			list_update_security.add_row([ txt ])

		else:
			try:
				available_security_updates = self.updater.get_all_available_security_updates()
			except (socket.error, socket.gaierror), e:
				ud.debug(ud.ADMIN, ud.ERROR, 'updater: socket.gaierror: %s' % traceback.format_exc().replace('%','§'))
				errormsg = _( 'The connection to the repository server failed: %s. Please check the repository settings and the network connection.' ) % str( e[ 1 ] )
			except Exception, e:
				ud.debug(ud.ADMIN, ud.ERROR, 'updater: %s' % traceback.format_exc().replace('%','§'))
				errormsg = _( 'An error occured during network operation: %s' % traceback.format_exc())

			if errormsg:
				list_update_security.add_row([ errormsg ])
			else:
				if available_security_updates:
					btn_install_security_update = umcd.Button(_('Install available security updates'), 'actions/install', actions = [umcd.Action(self.__get_warning_request({'type': 'security'}))])
					txt = _('The currently installed security update version is %(old)s and the most recent security update version is %(new)s.')
					list_update_security.add_row([umcd.Text(txt % {'old':self.updater.security_patchlevel, 'new': available_security_updates[-1].replace('sec','') })])
					list_update_security.add_row([btn_install_security_update])
				else:
					txt = umcd.Text( _('The currently installed security update version is %(old)s and no further security updates are available.') % { 'old': self.updater.security_patchlevel } )
					txt['colspan'] = '2'
					list_update_security.add_row([ txt ])

		# ==== UCS PACKAGE UPDATES =====
		list_update_packages = umcd.List()

		if self.__is_updater_running() or self.__is_security_update_running():
			# disable buttons if update is running
			list_update_packages.add_row([ umcd.Text('Check for new packages has been skipped since an update is currently running.') ])

		elif self.__is_dist_upgrade_running():
			# show button for logfile if update is running
			req = self.__get_logfile_request( { 'windowtype': 'dist-upgrade' } )
			btn_show_logfile = umcd.Button( _( 'View logfile' ), 'actions/install', actions = [ umcd.Action( req ) ] )
			list_update_packages.add_row([umcd.Text(_('The package update is still in progress.')), btn_show_logfile])

		else:
			# check for new packages
			req = umcp.Command(args=['update/components_update'], opts={'status': 'check'})
			req.set_flag('web:startup', True)
			req.set_flag('web:startup_cache', False)
			req.set_flag('web:startup_dialog', True)
			req.set_flag('web:startup_referrer', False)
			req.set_flag('web:startup_format', _('Check for package updates'))
			btn_update_check = umcd.Button(_('Check for package updates'), 'actions/refresh', actions = [umcd.Action(req)])

			txt = umcd.Text(_('%d component(s) have been specified and may contain new packages.') % len(self.updater.get_all_components()))
			txt['colspan'] = '2'
			list_update_packages.add_row([txt])
			list_update_packages.add_row([btn_update_check])

		frame_update_release = umcd.Frame([list_update_release], _('Release updates'))
		frame_update_security = umcd.Frame([list_update_security], _('Security updates'))
		frame_update_packages = umcd.Frame([list_update_packages], _('Package updates'))

		res.dialog = [frame_update_release, frame_update_security, frame_update_packages]
		if frame_info:
			res.dialog.insert( 0, frame_info )

		self.revamped(object.id(), res)


	def _web_release_settings(self, object, res):
		_d = ud.function('update.handler._web_release_settings')

		list_release = umcd.List()

		frame_release = umcd.Frame([list_release], _('Release settings'))
		inpt_server = umcd.make(self['update/release_settings']['repository_server'], default = self.updater.repository_server)
		inpt_prefix = umcd.make(self['update/release_settings']['repository_prefix'], default = self.updater.repository_prefix)
		inpt_hotfixes = umcd.make( self[ 'update/release_settings' ][ 'use_hotfixes' ], default = self.updater.hotfixes )
		inpt_maintained = umcd.make( self[ 'update/release_settings' ][ 'use_maintained' ], default = 'maintained' in self.updater.parts )
		inpt_unmaintained = umcd.make( self[ 'update/release_settings' ][ 'use_unmaintained' ], default = 'unmaintained' in self.updater.parts )

		list_release.add_row( [ inpt_server, inpt_prefix ] )
		list_release.add_row( [ '', '' ] )
		list_release.add_row( [ inpt_maintained, inpt_unmaintained ] )
		list_release.add_row( [ inpt_hotfixes, '' ] )
		req = umcp.Command(args = ['update/release_settings'])
		cancel = umcd.CancelButton()
		list_release.add_row( [ '', '' ] )
		list_release.add_row( [ cancel, umcd.SetButton( umcd.Action( req, [ inpt_server.id(), inpt_prefix.id(), inpt_hotfixes.id(), inpt_maintained.id(), inpt_unmaintained.id() ] ) ) ] )

		res.dialog = [frame_release]

		self.revamped(object.id(), res)

	def _web_settings(self, object, res):
		_d = ud.function('update.handler._web_settings')

		if self.__is_updater_running() or self.__is_security_update_running() or self.__is_dist_upgrade_running():
			lst = umcd.List()
			lst.add_row([ umcd.Text('The settings dialog has been disabled since an update is currently running. It will be reenabled if update process has finished.') ])
			res.dialog = [ umcd.Frame( [lst], _('Settings') ) ]
		else:
			# RELEASE SETTINGS
			list_settings_release = umcd.List()
			req = umcp.Command(args=['update/release_settings'])
			req.set_flag('web:startup', True)
			req.set_flag('web:startup_cache', False)
			req.set_flag('web:startup_dialog', True)
			req.set_flag('web:startup_referrer', True)
			req.set_flag('web:startup_format', _('Repository Settings'))
			btn_release = umcd.Button(_('Configure repository settings'), 'update/gear', actions=[umcd.Action(req)])
			list_settings_release.add_row([ _('UCS systems access repository servers for installing release updates or security updates.') ])
			list_settings_release.add_row([ _('Which repository server is used can be set for each UCS system individually.')  ])
			list_settings_release.add_row([ btn_release ])

			# COMPONENT SETTINGS
			list_settings_component_txt = umcd.List()
			list_settings_component_txt.add_row([ _('In addition to the standard repositories, additional software components can also be integrated by adding component repositories.') ])

			local_repo = self.updater.configRegistry.get( 'local/repository', 'no' ).lower() in ( 'yes', 'true' )
			if local_repo:
				list_settings_component.add_row( [ umcd.InfoBox( _( 'The component management has been deactivated as this server has a local repository.' ), columns = 2 ) ] )
			else:
				list_settings_component = umcd.List()
				list_settings_component.set_header( [ _('Component Name'), _( 'Status' ), '' ] )
				for component_name in self.updater.get_all_components():
					component = self.updater.get_component(component_name)
					description = component.get('description', component_name)
					req = umcp.Command(args=['update/components_settings'], opts = {'component': component})
					req.set_flag('web:startup', True)
					req.set_flag('web:startup_cache', False)
					req.set_flag('web:startup_dialog', True)
					req.set_flag('web:startup_referrer', True)
					req.set_flag('web:startup_format', _('Modify component %s' )  % description )
					txt = umcd.Text(_('This component is disabled.'))
					if component.get('activated', '').lower() in ['true', 'yes', '1', 'enabled']:
						txt = umcd.Text(_('This component is enabled.'))
					btn = umcd.Button(_('Configure'), 'update/gear', actions=[umcd.Action(req)])
					list_settings_component.add_row([ umcd.Text(description), txt, btn ])

				req = umcp.Command(args=['update/components_settings'])
				req.set_flag('web:startup', True)
				req.set_flag('web:startup_cache', False)
				req.set_flag('web:startup_dialog', True)
				req.set_flag('web:startup_referrer', True)
				req.set_flag('web:startup_format', _('Add a new component'))
				btn_add_component = umcd.Button(_('Add a new component'), 'actions/plus', actions = [umcd.Action(req)])
				btn_add_component['colspan'] = '2'
				list_settings_component.add_row([ btn_add_component ])

			res.dialog = [ umcd.Frame([list_settings_release], _('Repository settings')), umcd.Frame([list_settings_component_txt, list_settings_component], _('Component settings')) ]
		self.revamped(object.id(), res)



	def _web_components_settings(self, object, res):
		_d = ud.function('update.handler._web_components_settings res=%s' % res.options)

		activated = False
		name = ''
		description = ''
		server = ''
		prefix = ''
		username = ''
		password = ''
		parts = [ 'maintained' ]

		# build the default values
		if res.options.has_key('component'):
			activated_component = res.options['component'].get('activated', '')
			if activated_component.lower() in ['true', 'yes', '1', 'enabled']:
				activated = True
			else:
				activated = False

			name = res.options['component'].get('name', '')
			description = res.options['component'].get('description', '')
			server = res.options['component'].get('server', '')
			prefix = res.options['component'].get('prefix', '')
			username = res.options['component'].get('username', '')
			password = res.options['component'].get('password', '')
			parts = re.split('[, ]', res.options['component'].get('parts', 'maintained'))

		if not server:
			server=self.updater.repository_server
		if not prefix:
			prefix=self.updater.repository_prefix


		list_release = umcd.List()

		frame_release = umcd.Frame([list_release], _('Component settings'))

		inpt_activated = umcd.make(self['update/components_settings']['component_activated'], default = activated)
		inpt_name = umcd.make(self['update/components_settings']['component_name'], default = name)
		inpt_description = umcd.make(self['update/components_settings']['component_description'], default = description)
		# TODO: add a check button
		inpt_server = umcd.make(self['update/components_settings']['component_server'], default = server)
		inpt_prefix = umcd.make(self['update/components_settings']['component_prefix'], default = prefix)
		inpt_username = umcd.make(self['update/components_settings']['component_username'], default = username)
		inpt_password = umcd.make(self['update/components_settings']['component_password'], default = password)
		inpt_maintained = umcd.make( self[ 'update/components_settings' ][ 'use_maintained' ], default = 'maintained' in parts )
		inpt_unmaintained = umcd.make( self[ 'update/components_settings' ][ 'use_unmaintained' ], default = 'unmaintained' in parts )

		list_release.add_row([inpt_activated])
		list_release.add_row([inpt_name, inpt_description])
		list_release.add_row([inpt_server, inpt_prefix])
		list_release.add_row([inpt_username, inpt_password])
		list_release.add_row([inpt_maintained, inpt_unmaintained])

		req = umcp.Command(args = ['update/components_settings'])
		cancel = umcd.CancelButton()
		list_release.add_row([umcd.SetButton(umcd.Action(req, [inpt_activated.id(), inpt_name.id(), inpt_description.id(), inpt_server.id(),
															   inpt_prefix.id(), inpt_username.id(), inpt_password.id(), inpt_maintained.id(),
															   inpt_unmaintained.id()])), cancel])


		res.dialog = [frame_release]
		self.revamped(object.id(), res)

	def _web_components_update(self, object, res):
		_d = ud.function('update.handler._web_components_update')

		result = umcd.List()

		if object.options['status'] == 'check':
			if len(res.dialog['text']) > 0:
				result.add_row([ umcd.HTML(res.dialog['text'], attributes = { 'colspan' : str(2) })])
				req = umcp.Command(args=['update/components_update'], opts={'status': 'warning'})
				req.set_flag('web:startup', True)
				req.set_flag('web:startup_cache', False)
				req.set_flag('web:startup_dialog', True)
				req.set_flag('web:startup_referrer', False)
				req.set_flag('web:startup_format', _('Confirm the updater warning'))
				btn_continue = umcd.Button(_('Continue'), 'actions/ok', actions = [umcd.Action(req)])

				result.add_row([ btn_continue, umcd.CancelButton()])
			else:
				result.add_row([ umcd.HTML('<h2>' + _('No updates available') + '</h2>')])
				result.add_row([ umcd.CancelButton()])
		elif object.options['status'] == 'warning':
			html = self.__get_update_warning()

			result.add_row([ umcd.HTML(html, attributes = { 'colspan' : str(2) })])
			req = umcp.Command(args=['update/components_update'], opts={'status': 'execute'})
			req.set_flag('web:startup', True)
			req.set_flag('web:startup_cache', False)
			req.set_flag('web:startup_dialog', True)
			req.set_flag('web:startup_referrer', False)
			req.set_flag('web:startup_format', _('Execute the update'))
			tail_action = umcd.Action(self.__get_logfile_request( { 'windowtype': 'dist-upgrade' } ))
			btn_continue = umcd.Button(_('Continue'), 'actions/ok', actions = [umcd.Action(req), tail_action])

			result.add_row([ btn_continue, umcd.CancelButton()])
		elif object.options['status'] == 'execute':
			pass

		res.dialog = [ result]
		self.revamped(object.id(), res)

	def _web_update_warning(self, object, res):
		_d = ud.function('update.handler._web_update_warning')

		result = umcd.List()

		if res.options['type'] == 'security':
			command = 'update/install_security_updates'
		else:
			command = 'update/install_release_updates'

		html = self.__get_update_warning()

		updateto = object.options.get('updateto',[None])
		ud.debug(ud.ADMIN, ud.PROCESS, '_web_update_warning: updateto=%s' % updateto )

		result.add_row([ umcd.HTML(html, attributes = { 'colspan' : str(2) })])
		req = umcp.Command(args=[command], opts={ 'updateto': updateto } )
		btn_continue = umcd.Button(_('Continue'), 'actions/ok', actions = [umcd.Action(req), umcd.Action(self.__get_logfile_request( { 'windowtype': res.options['type'] } ))])

		result.add_row([ btn_continue, umcd.CancelButton()])
		res.dialog = [ result]
		self.revamped(object.id(), res)


	#######################
	# Some helper scripts
	#######################

	def __create_at_job(self, command):
		script = '''
dpkg-statoverride --add root root 0644 /usr/sbin/univention-management-console-server
dpkg-statoverride --add root root 0644 /usr/sbin/apache2
chmod -x /usr/sbin/univention-management-console-server /usr/sbin/apache2
%s < /dev/null
if [ $? -eq 0 ]; then
	univention-config-registry set update/reboot/required=yes
fi
dpkg-statoverride --remove /usr/sbin/univention-management-console-server
dpkg-statoverride --remove /usr/sbin/apache2
chmod +x /usr/sbin/univention-management-console-server /usr/sbin/apache2
''' % command
		p1 = subprocess.Popen( [ 'LC_ALL=C at now', ], stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE, shell = True )
		(stdout,stderr) = p1.communicate( script )
		ud.debug(ud.ADMIN, ud.WARN, 'executing "%s"' % command)
		ud.debug(ud.ADMIN, ud.WARN, 'install stderr=%s' % stderr)
		ud.debug(ud.ADMIN, ud.INFO, 'install stdout=%s' % stdout)
		match = re.search('^job\s+(\d+)\s+at', stdout, re.I | re.S | re.M)
		if match:
			ud.debug(ud.ADMIN, ud.INFO, 'created at job %s' % match.group(1))

		if p1.returncode != 0:
			return (p1.returncode,stderr)
		else:
			return (p1.returncode,stdout)

	def __is_process_running(self, command ):
		p1 = subprocess.Popen('/usr/bin/atq', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		(atqout,stderr) = p1.communicate()
		for line in atqout.splitlines():
			job = line.split('\t',1)[0]
			if job.isdigit():
				p2 = subprocess.Popen(['/usr/bin/at','-c',job], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
				(atout,stderr) = p2.communicate()
				if command in atout:
					return True
		return False

	def __is_updater_running(self):
		return self.__is_process_running( 'univention-updater net' )


	def __is_security_update_running(self):
		return self.__is_process_running( 'univention-security-update net' )


	def __is_dist_upgrade_running(self):
		return self.__is_process_running( self.command_dist_upgrade )


	def __remove_status_messages(self, text):
		result = []
		for line in text.split('\n'):
			if line.startswith('\r'):
				continue
			result.append(line)
		return string.join(result, '\n').replace('\n', '<br />')


	def __get_update_warning(self):
		html = '<h2>' + _('Attention!') + '</h2>' + '<body>'
		html += _('Installing an system update is a significant change to your IT environment.<br>')
		html += _('In the normal case, undisturbed use operation cannot be guaranteed during the update,<br>')
		html += _('since system services may need to be restarted. Thus, updates shouldn\'t be installed<br>')
		html += _('on a live system. It is also recommend to evaluate the update in a test environment<br>')
		html += _('and to create a backup of the system.')
		html += '<br><br>'
		html += _('During setup, the web server may be stopped, leading to a termination of the HTTP<br>')
		html += _('connection. Nonetheless, the update proceeds and the update can be monitored from a<br>')
		html += _('new UMC session. Logfiles can be found in the directory /var/log/univention/.')
		html += '<br><br>'
		html += _('Please also consider the release notes, changelogs and references posted in the<br>')
		html += _('<a href=http://forum.univention.de>Univention Forum</a>.')
		html += '<br><br>'
		html += _('Do you really wish to proceed?')
		html += '<br><br>'
		html += '</body>'

		return html


	def __get_logfile_request( self, options ):
		req = umcp.Command( args = [ 'update/tail_logfile_dialog' ] )
		req.options.update(options)
		req.set_flag('web:startup', True)
		req.set_flag('web:startup_cache', False)
		req.set_flag('web:startup_dialog', True)
		req.set_flag('web:startup_referrer', False)
		req.set_flag('web:startup_format', _('Update progress'))

		return req

	def __get_warning_request(self, options = None):
		req = umcp.Command(args=['update/update_warning'], opts = options)
		req.set_flag('web:startup', True)
		req.set_flag('web:startup_cache', False)
		req.set_flag('web:startup_dialog', True)
		req.set_flag('web:startup_referrer', False)
		req.set_flag('web:startup_format', _('Update warning'))
		return req
