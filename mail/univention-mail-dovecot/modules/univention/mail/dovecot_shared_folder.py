# -*- coding: utf-8 -*-
#
# Univention Mail Dovecot - shared code for listeners
#
# Copyright 2015 Univention GmbH
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

import os
import os.path
import subprocess
import re
import traceback
import imaplib
import shutil

import univention.admin.modules
from univention.uldap import getMachineConnection
from univention.config_registry import handler_set
from univention.mail.dovecot import DovecotListener


# UDM name → (IMAP, doveadm)
dovecot_acls = {
	"read":   ("lrws",     ["lookup", "read", "write", "write-seen"]),
	"post":   ("lrwsp",    ["lookup", "read", "write", "write-seen", "post"]),
	"append": ("lrwspi",   ["lookup", "read", "write", "write-seen", "post", "insert"]),
	"write":  ("lrwspit",  ["lookup", "read", "write", "write-seen", "post", "insert", "write-deleted"]),
	"all":    ("lrwspita", ["lookup", "read", "write", "write-seen", "post", "insert", "write-deleted", "admin"])}


class DovecotSharedFolderListener(DovecotListener):
	def __init__(self, *args, **kwargs):
		super(DovecotSharedFolderListener, self).__init__(*args, **kwargs)
		self.modules = ["mail/folder"]
		self.acl_key = "univentionMailACL"

	def add_shared_folder(self, new):
		if "mailPrimaryAddress" in new:
			# use a shared folder
			new_mailbox = new["mailPrimaryAddress"][0]
			# the maildir will be autocreated by dovecot
			acls = new.get(self.acl_key, [])
			# Even if there are no ACL entries, we must still _change_ at
			# least one entry through IMAP, so the shared mailbox list
			# dictionary is updated. Lets remove the (afterwards) unnecessary
			# master-user entry.
			acls.append("dovecotadmin none")
			try:
				# give master-user admin rights on mailbox
				self.doveadm_set_mailbox_acls("shared/%s" % new_mailbox, ["dovecotadmin all"])
				# use IMAP to set actual ACLs, so the shared mailbox list dictionary is updated
				self.imap_set_mailbox_acls(new_mailbox, "INBOX", acls)
			except:
				self.log_e("Failed setting ACLs on new shared mailbox '%s'." % new_mailbox)
				return
			self.log_p("Created shared mailbox '%s'." % new_mailbox)
		else:
			# use a public folder
			new_mailbox = new["cn"][0]
			try:
				self.update_public_mailbox_configuration()
				self.create_public_folder(new_mailbox)
				acls = new.get(self.acl_key)
				if acls:
					self.doveadm_set_mailbox_acls("%s/INBOX" % new_mailbox, acls)
					self.log_p("Set ACLs on '%s'." % new_mailbox)
			except:
				self.log_e("Failed creating public mailbox '%s'." % new_mailbox)
				return
			self.log_p("Created public mailbox '%s'." % new_mailbox)

	def del_shared_folder(self, old):
		if "mailPrimaryAddress" in old:
			# shared folder
			old_mailbox = old["mailPrimaryAddress"][0]
			old_loc, old_domain = old_mailbox.split("@")
			global_mail_home = self.get_maillocation()
			path = str(global_mail_home).replace("%Ld", old_domain).replace("%Ln", old_loc)
			# cannot unsubscribe to non-existing shared folder (a.k.a. private mailbox)
		else:
			# public folder
			old_mailbox = old["cn"][0]
			old_loc, old_domain = old_mailbox.split("@")
			path = self.get_public_location(old_mailbox)
			if self.acl_key in old:
				# Only users with ACL entries can potentially have subscribed, unsubscribe them.
				# For performance reasons this intentionally ignores groups.
				folder = "%s/INBOX" % old_mailbox
				self.unsubscribe_from_mailbox([acl.split()[0] for acl in old[self.acl_key] if "@" in acl.split()[0]], folder)
			# update namespaces
			self.update_public_mailbox_configuration(delete_only=old_mailbox)

		# remove mailbox from disk
		if self.listener.configRegistry.is_true("mail/dovecot/mailbox/delete", False):
			try:
				self.listener.setuid(0)
				shutil.rmtree(path, ignore_errors=True)
			except:
				self.log_e("Error deleting mailbox '%s'." % old_mailbox)
				return
			finally:
				self.listener.unsetuid()
			self.log_p("Deleted mailbox '%s'." % old_mailbox)
		else:
			self.log_p("Deleting of mailboxes disabled (mailbox '%s')." % old_mailbox)

	def mod_shared_folder(self, old, new):
		if "mailPrimaryAddress" in new:
			# use a shared folder
			new_mailbox = new["mailPrimaryAddress"][0]

			if "mailPrimaryAddress" in old:
				# it remains a shared folder
				old_mailbox = old["mailPrimaryAddress"][0]
				if new_mailbox != old_mailbox:
					# rename/move mailbox inside private namespace
					#
					# cannot unsubscribe to non-existing shared folder (a.k.a. private mailbox)
					self.move_user_home(new_mailbox, old_mailbox, True)
					self.log_p("Moved mailbox '%s' -> '%s'." % (old_mailbox, new_mailbox))
				else:
					# no address change
					pass
			else:
				# move mailbox from public to private namespace
				self.log_p("Moving mailbox from public to private namespace...")
				old_mailbox = old["cn"][0]
				try:
					pub_loc = self.get_public_location(old_mailbox)
					new_user_home = self.get_user_home(new_mailbox)
					if self.acl_key in old:
						old_acl_users = [acl.split()[0] for acl in old[self.acl_key] if "@" in acl.split()[0]]
						self.unsubscribe_from_mailbox(old_acl_users, "%s/INBOX" % old_mailbox)
					# update dovecot config
					self.update_public_mailbox_configuration()
					# move mail home
					self.move_mail_home(pub_loc, new_user_home, new_mailbox, True)
					old_maildir = os.path.join(new_user_home, ".INBOX")
					new_maildir = os.path.join(new_user_home, "Maildir")
					try:
						# rename mailbox
						self.listener.setuid(0)
						shutil.move(old_maildir, new_maildir)
					except:
						self.log_e("Failed to move mail home (of '%s') from '%s' to '%s'.\n%s" % (
							new_mailbox, old_maildir, new_maildir, traceback.format_exc()))
						raise
					finally:
						self.listener.unsetuid()
				except:
					self.log_e("Could not rename/move mailbox ('%s' -> '%s').\n%s" % (old_mailbox, new_mailbox, traceback.format_exc()))
					return
				self.log_p("Moved mailbox '%s' -> '%s'." % (old_mailbox, new_mailbox))

			# set ACLs
			acls = new.get(self.acl_key, [])
			# Even if there are no ACL entries, we must still _change_ at
			# least one entry through IMAP, so the shared mailbox list
			# dictionary is updated. Lets remove the (afterwards) unnecessary
			# master-user entry.
			acls.append("dovecotadmin none")
			try:
				# give master-user admin rights on mailbox, so it can change its ACL
				self.doveadm_set_mailbox_acls("shared/%s" % new_mailbox, ["dovecotadmin all"])
				# use IMAP to set actual ACLs, so the shared mailbox list dictionary is updated
				self.imap_set_mailbox_acls(new_mailbox, "INBOX", acls)
			except:
				self.log_e("Failed setting ACLs on moved shared mailbox ('%s' -> '%s')." % (old_mailbox, new_mailbox))
				return
			self.log_p("Set ACLs on '%s'." % new_mailbox)
		else:
			# use a public folder
			new_mailbox = new["cn"][0]
			if "mailPrimaryAddress" in old:
				# move mailbox from private to public namespace
				self.log_p("Moving mailbox from private to public namespace...")
				old_mailbox = old["mailPrimaryAddress"][0]
				old_loc, old_domain = old_mailbox.split("@")
				# cannot unsubscribe to non-existing shared folder (a.k.a. private mailbox)
				try:
					global_mail_home = self.get_maillocation()
					old_path = str(global_mail_home).replace("%Ld", old_domain).replace("%Ln", old_loc).lower()
					# update dovecot config
					self.update_public_mailbox_configuration()
					pub_loc = self.get_public_location(new_mailbox)
					# move mail home
					self.move_mail_home(old_path, pub_loc, new_mailbox, True)
					old_maildir = os.path.join(pub_loc, "Maildir")
					new_maildir = os.path.join(pub_loc, ".INBOX")
					try:
						# rename mailbox
						self.listener.setuid(0)
						shutil.move(old_maildir, new_maildir)
					except:
						self.log_e("Failed to move mail home (of '%s') from '%s' to '%s'.\n%s" % (
							new_mailbox, old_maildir, new_maildir, traceback.format_exc()))
						raise
					finally:
						self.listener.unsetuid()
				except:
					self.log_e("Could not rename/move mailbox ('%s' -> '%s').\n%s" % (old_mailbox, new_mailbox, traceback.format_exc()))
					return
				self.log_p("Moved mailbox '%s' -> '%s'." % (old_mailbox, new_mailbox))
			else:
				# it remained a public folder
				# renaming of public folders is disabled in UDM
				# quota may have changed, update dovecot config
				self.update_public_mailbox_configuration()

			# set ACLs
			try:
				if self.acl_key in old and self.acl_key not in new:
					# remove all ACL entries for this mailbox
					acls = old.get(self.acl_key)
					if acls:
						self.doveadm_set_mailbox_acls("%s/INBOX" % new_mailbox, ["%s none" % x.split()[0] for x in acls])
				else:
					curacl = {}
					# find new ACLs
					for acl in new.get(self.acl_key, []):
						right = acl.split()[-1]
						identifier = " ".join(acl.split()[:-1])
						curacl[identifier] = right
					# remove old ACLs
					for acl in old.get(self.acl_key, []):
						identifier = " ".join(acl.split()[:-1])
						if identifier not in curacl:
							curacl[identifier] = "none"
					self.doveadm_set_mailbox_acls("%s/INBOX" % new_mailbox, ["%s %s" % (identifier_, right_) for identifier_, right_ in curacl.items()])
			except:
					self.log_e("Error changing ACLs for mailbox '%s'." % new_mailbox)
			self.log_p("Set ACLs on '%s'." % new_mailbox)

	def get_public_location(self, ns):
		try:
			pub_loc = self.read_from_ext_proc_as_root(["/usr/bin/doveconf", "-h", "namespace/" + ns + "/location"], "maildir:(\S+):INDEXPVT.*")
		except:
			self.log_e("Failed to get location of public folder '%s' from Dovecot configuration.\n%s" % (ns, traceback.format_exc()))
			raise
		return pub_loc

	def create_public_folder(self, folder_name):
		try:
			user, group = self.get_dovecot_user()
			pub_loc = self.get_public_location(folder_name)
			path = os.path.join(pub_loc, ".INBOX")
			self.mkdir_p(pub_loc)
			self.read_from_ext_proc_as_root(["/usr/bin/maildirmake.dovecot", path, "%s:%s" % (user, group)])
			self.listener.setuid(0)
		except:
			self.log_e("Failed to create maildir '%s'." % folder_name)
			raise
		finally:
			self.listener.unsetuid()
		return path

	def read_from_ext_proc_as_root(self, cmd, regexp=None, stdin=None, stdout=subprocess.PIPE, stderr=None, stdin_input=None):
		"""
		Wrapper around Popen(), runs external command as root and return its
		output, optionally the first hit of a regexp. May raise an exception.

		:param cmd: list: with executable path as first item
		:param regexp: string: regexp for re.findall()
		:return: string
		"""
		try:
			self.listener.setuid(0)
			cmd_proc = subprocess.Popen(cmd, stdin=stdin, stdout=stdout, stderr=stderr)
			cmd_out, cmd_err = cmd_proc.communicate(input=stdin_input)
			cmd_exit = cmd_proc.wait()
			if cmd_out and not cmd_err and cmd_exit == 0:
				if regexp:
					res = re.findall(regexp, cmd_out)
					return res[0]
				else:
					return cmd_out.rstrip()
		finally:
			self.listener.unsetuid()

	def doveadm_set_mailbox_acls(self, mailbox, acls):
		for acl in acls:
			right = acl.split()[-1]
			identifier = " ".join(acl.split()[:-1])
			if "@" in identifier or identifier == "dovecotadmin":
				identifier = "user=" + identifier
			elif identifier in ["anyone", "authenticated"]:
				pass
			else:
				identifier = "group=" + identifier

			if right == "none":
				cmd = ["/usr/bin/doveadm", "acl", "delete", "-u", "Administrator", mailbox, identifier]
			else:
				cmd = ["/usr/bin/doveadm", "acl", "set", "-u", "Administrator", mailbox, identifier]
				cmd.extend(dovecot_acls[right][1])
			try:
				self.read_from_ext_proc_as_root(cmd)
			except:
				self.log_e("Failed to set ACL using doveadm using command '%s'." % cmd)
				raise
		return

	def imap_set_mailbox_acls(self, mb_owner, mailbox, acls):
		master_name, master_pw = self.get_masteruser_credentials()
		imap = None
		try:
			imap = imaplib.IMAP4("localhost")
			imap.login("%s*%s" % (mb_owner, master_name), master_pw)
			for acl in acls:
				right = acl.split()[-1]
				identifier = " ".join(acl.split()[:-1])
				if "@" in identifier or identifier in ["anyone", "authenticated", "dovecotadmin"]:
					pass
				else:
					# group
					identifier = "$" + identifier
				if right == "none":
					imap.deleteacl(mailbox, identifier)
				else:
					imap.setacl(mailbox, identifier, dovecot_acls[right][0])
		except:
			self.log_e("Failed to set ACLs '%s' on mailbox '%s' for '%s'.\n%s" % (acls, mailbox, mb_owner, traceback.format_exc()))
			raise
		finally:
			if imap:
				imap.logout()

	def update_public_mailbox_configuration(self, delete_only=None):
		"""
		Cache public folders and their quota into a UCRV.

		:param delete_only: if True removes only entry 'delete_only', else recreates from scratch.
		:return: None
		"""

		#TODO: create distinct configurations for each server (honor univentionMailHomeServer)

		# When deleting, remove only one entry, so in the case of multi-remove
		# subsequent code can still access the remaining namespace configuration.
		# In any other case (add/modify) recreate from scratch to ensure
		# consistency with the LDAP.
		if delete_only:
			try:
				self.listener.setuid(0)
				old_info = self.listener.configRegistry.get("mail/dovecot/internal/sharedfolders", "").split()
				emails_quota = [info for info in old_info if not info.startswith(delete_only + ":")]
			except:
				self.log_e("update_public_mailbox_configuration(): Failed to update public mailbox configuration:\n%s" % traceback.format_exc())
				raise
			finally:
				self.listener.unsetuid()
		else:
			public_folders = list()
			for module in self.modules:
				try:
					public_folders.extend(self.get_udm_infos(module, "(!(mailPrimaryAddress=*))"))
				except:
					self.log_e("update_public_mailbox_configuration(): Failed to update public mailbox configuration:\n%s" % traceback.format_exc())
					raise
				finally:
					self.listener.unsetuid()
			emails_quota = ["%s@%s:%s" % (pf["name"] or pf.dn.split("@")[0].split("=")[1],
						pf["mailDomain"],
						pf.get("univentionMailUserQuota", 0) or pf.get("cyrus-userquota", 0))
						for pf in public_folders]
		try:
			self.listener.setuid(0)
			handler_set(["mail/dovecot/internal/sharedfolders=%s" % " ".join(emails_quota)])
			self.read_from_ext_proc_as_root(["/usr/bin/doveadm", "reload"])
		except:
			self.log_e("update_public_mailbox_configuration(): Failed to update public mailbox configuration:\n%s" % traceback.format_exc())
			raise
		finally:
			self.listener.unsetuid()
		self.log_p("Updated shared mailbox configuration.")

	def unsubscribe_from_mailbox(self, users, mailbox):
		for user in users:
			try:
				self.read_from_ext_proc_as_root(["/usr/bin/doveadm", "mailbox", "unsubscribe", "-u", user, mailbox])
			except:
				self.log_e("Failed to unsubscribe user '%s' from mailbox '%s'." % (user, mailbox))

	def get_udm_infos(self, udm_module, udm_filter):
		try:
			self.listener.setuid(0)
			univention.admin.modules.update()
			lo = getMachineConnection()
			config = univention.admin.config.config()
			mod = univention.admin.modules.get(udm_module)
			return mod.lookup(config, lo, udm_filter)
		except:
			self.log_e("get_udm_infos(%s, %s): Failed to retrieve UDM info:\n%s" % (udm_module, udm_filter, traceback.format_exc()))
			raise
		finally:
			self.listener.unsetuid()