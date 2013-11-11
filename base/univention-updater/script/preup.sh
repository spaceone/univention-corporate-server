#!/bin/bash
#
# Copyright (C) 2010-2013 Univention GmbH
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

export DEBIAN_FRONTEND=noninteractive

UPDATER_LOG="/var/log/univention/updater.log"
exec 3>>"$UPDATER_LOG"
UPDATE_NEXT_VERSION="$1"

echo "Running preup.sh script" >&3
date >&3

eval "$(univention-config-registry shell)" >&3 2>&3

conffile_is_unmodified () {
	# conffile_is_unmodified <conffile>
	# returns exitcode 0 if given conffile is unmodified
	if [ ! -f "$1" ]; then
		return 1
	fi
	local chksum="$(md5sum "$1" | awk '{ print $1 }')"
	local fnregex="$(python -c 'import re,sys;print re.escape(sys.argv[1])' "$1")"
	for testchksum in $(dpkg-query -W -f '${Conffiles}\n' | sed -nre "s,^ $fnregex ([0-9a-f]+)( .*)?$,\1,p") ; do
		if [ "$testchksum" = "$chksum" ] ; then
			return 0
		fi
	done
	return 1
}

readcontinue ()
{
    while true ; do
        echo -n "Do you want to continue [Y/n]? "
        read var
        if [ -z "$var" -o "$var" = "y" -o "$var" = 'Y' ]; then
            return 0
        elif [ "$var" = "n" -o "$var" = 'N' ]; then
            return 1
        else
            echo ""
            continue
        fi
    done
}

###########################################################################
# RELEASE NOTES SECTION (Bug #19584)
# Please update URL to release notes and changelog on every release update
###########################################################################
echo
echo "HINT:"
echo "Please check the release notes carefully BEFORE updating to UCS ${UPDATE_NEXT_VERSION}:"
echo " English version: http://download.univention.de/doc/release-notes-3.2-0_en.pdf"
echo " German version:  http://download.univention.de/doc/release-notes-3.2-0.pdf"
echo
echo "Please also consider documents of following release updates and"
echo "3rd party components."
echo
if [ ! "$update_warning_releasenotes" = "no" -a ! "$update_warning_releasenotes" = "false" -a ! "$update_warning_releasenotes_internal" = "no" ] ; then
	if [ "$UCS_FRONTEND" = "noninteractive" ]; then
		echo "Update will wait here for 60 seconds..."
		echo "Press CTRL-c to abort or press ENTER to continue"
		# BUG: 'read -t' is the only bash'ism in this file, therefore she-bang has to be /bin/bash not /bin/sh!
		read -t 60 somevar
	else
		readcontinue || exit 1
	fi
fi

echo ""

# check if user is logged in using ssh
if [ -n "$SSH_CLIENT" ]; then
	if [ "$update32_ignoressh" != "yes" ]; then
		echo "WARNING: You are logged in using SSH -- this may interrupt the update and result in an inconsistent system!"
		echo "Please log in under the console or re-run with \"--ignoressh\" to ignore it."
		exit 1
	fi
fi

if [ "$TERM" = "xterm" ]; then
	if [ "$update32_ignoreterm" != "yes" ]; then
		echo "WARNING: You are logged in under X11 -- this may interrupt the update and result in an inconsistent system!"
		echo "Please log in under the console or re-run with \"--ignoreterm\" to ignore it."
		exit 1
	fi
fi

# save ucr settings
updateLogDir="/var/univention-backup/update-to-$UPDATE_NEXT_VERSION"
if [ ! -d "$updateLogDir" ]; then
	mkdir -p "$updateLogDir"
fi
cp /etc/univention/base*.conf "$updateLogDir/" 
ucr dump > "$updateLogDir/ucr.dump"

# call custom preup script if configured
if [ ! -z "$update_custom_preup" ]; then
	if [ -f "$update_custom_preup" ]; then
		if [ -x "$update_custom_preup" ]; then
			echo "Running custom preupdate script $update_custom_preup"
			"$update_custom_preup" "$UPDATE_NEXT_VERSION" >&3 2>&3
			echo "Custom preupdate script $update_custom_preup exited with exitcode: $?" >&3
		else
			echo "Custom preupdate script $update_custom_preup is not executable" >&3
		fi
	else
		echo "Custom preupdate script $update_custom_preup not found" >&3
	fi
fi

# shell-univention-lib is proberly not installed, so use a local function
is_ucr_true () {
    local value
    value="$(/usr/sbin/univention-config-registry get "$1")"
    case "$(echo -n "$value" | tr [:upper:] [:lower:])" in
        1|yes|on|true|enable|enabled) return 0 ;;
        0|no|off|false|disable|disabled) return 1 ;;
        *) return 2 ;;
    esac
}

## check for hold packages 
hold_packages=$(LC_ALL=C dpkg -l | grep ^h | awk '{print $2}')
if [ -n "$hold_packages" ]; then
	echo "WARNING: Some packages are marked as hold -- this may interrupt the update and result in an inconsistent"
	echo "system!"
	echo "Please check the following packages and unmark them or set the UCR variable update32/ignore_hold to yes"
	for hp in $hold_packages; do
		echo " - $hp"
	done
	if is_ucr_true update32/ignore_hold; then
		echo "WARNING: update32/ignore_hold is set to true. Skipped as requested."
	else
		exit 1
	fi
fi

##

#################### Bug #22093

get_latest_kernel_pkg () {
	# returns latest kernel package for given kernel version
	# currently running kernel is NOT included!

	kernel_version="$1"

	latest_dpkg=""
	latest_kver=""
	for kver in $(COLUMNS=200 dpkg -l linux-image-${kernel_version}-ucs\* 2>/dev/null | grep linux-image- | awk '{ print $2 }' | sort -n | grep -v "linux-image-$(uname -r)") ; do
		dpkgver="$(apt-cache show $kver | sed -nre 's/Version: //p')"
		if dpkg --compare-versions "$dpkgver" gt "$latest_dpkg" ; then
			latest_dpkg="$dpkgver"
			latest_kver="$kver"
		fi
	done
	echo "$latest_kver"
}

pruneOldKernel () {
	# removes all kernel packages of given kernel version
	# EXCEPT currently running kernel and latest kernel package
	# ==> at least one and at most two kernel should remain for given kernel version
	kernel_version="$1"

	ignore_kver="$(get_latest_kernel_pkg "$kernel_version")"
	DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Options::=--force-confold -y --force-yes remove --purge $(COLUMNS=200 dpkg -l linux-image-${kernel_version}-ucs\* 2>/dev/null | grep linux-image- | awk '{ print $2 }' | sort -n | egrep -v "linux-image-$(uname -r)|$ignore_kver" | tr "\n" " ") >>/var/log/univention/updater.log 2>&1
}

if [ "$update32_pruneoldkernel" = "yes" ]; then
	echo "Purging old kernel..." | tee -a /var/log/univention/updater.log
	pruneOldKernel "2.6.18"
	pruneOldKernel "2.6.26"
	pruneOldKernel "2.6.32"
	pruneOldKernel "3.2"
	echo "done" | tee -a /var/log/univention/updater.log
fi

#####################

check_space(){
	partition=$1
	size=$2
	usersize=$3
	echo -n "Checking for space on $partition: "
	if [ `df -P "$partition" | tail -n1 | awk '{print $4}'` -gt "$size" ]; then
		echo "OK"
	else
		echo "failed"
		echo "ERROR:   Not enough space in $partition, need at least $usersize."
		echo "         This may interrupt the update and result in an inconsistent system!"
		echo "         If neccessary you can skip this check by setting the value of the"
		echo "         config registry variable update32/checkfilesystems to \"no\"."
		echo "         But be aware that this is not recommended!"
		if [ "$partition" = "/boot" -a ! "$update32_pruneoldkernel" = "yes" ] ; then
			echo "         Old kernel versions on /boot can be pruned automatically during"
			echo "         next update attempt by setting config registry variable"
			echo "         update32/pruneoldkernel to \"yes\"."
		fi
		echo ""
		# kill the running univention-updater process
		exit 1
	fi
}


# move old initrd files in /boot
initrd_backup=/var/backups/univention-initrd.bak/
if [ ! -d "$initrd_backup" ]; then
	mkdir "$initrd_backup"
fi
mv /boot/*.bak /var/backups/univention-initrd.bak/ >/dev/null 2>&1

# check space on filesystems
if [ ! "$update32_checkfilesystems" = "no" ]
then

	check_space "/var/cache/apt/archives" "800000" "0,8 GB"
	check_space "/boot" "50000" "50 MB"
	check_space "/" "1300000" "1,3 GB"

else
    echo "WARNING: skipped disk-usage-test as requested"
fi


echo -n "Checking for package status: "
dpkg -l 2>&1 | LC_ALL=C grep "^[a-zA-Z][A-Z] " >&3 2>&3
if [ $? = 0 ]; then
	echo "failed"
	echo "ERROR: The package state on this system is inconsistent."
	echo "       Please run 'dpkg --configure -a' manually"
	exit 1
fi
echo "OK"

if [ -x /usr/sbin/slapschema ]; then
	echo -n "Checking LDAP schema: "
	if ! /usr/sbin/slapschema >&3 2>&3; then
		echo "failed"
		echo "ERROR: There is a problem with the LDAP schema on this system."
		echo "       Please check $UPDATER_LOG or run 'slapschema' manually."
		exit 1
	fi
	echo "OK"
fi

# check for valid machine account
if [ -f /var/univention-join/joined -a ! -f /etc/machine.secret ]
then
	echo "ERROR: The credentials for the machine account could not be found!"
	echo "       Please contact the support team"
	exit 1
fi

eval "$(ucr shell server/role ldap/base ldap/hostdn ldap/server/name)"
if [ -n "$server_role" -a "$server_role" != "basesystem" -a -n "$ldap_base" -a -n "$ldap_hostdn" ]
then
	ldapsearch -x -D "$ldap_hostdn" -w "$(< /etc/machine.secret)" -b "$ldap_base" -s base &>/dev/null
	if [ $? -eq 49 ]
	then
		echo "ERROR: A LDAP connection to the configured LDAP servers with the machine"
		echo "       account has failed (invalid credentials)!"
		echo "       This MUST be fixed before the update can continue."
		echo
		echo "       This problem can be corrected by setting the content of the file"
		echo "       /etc/machine.secret as the password of the computer object using"
		echo "       Univention Management Console."
		exit 1
	fi
fi

# check for deprecated MySQL option skip-bdb in modified configuration files
MYSQL_CONF="/etc/mysql/my.cnf"
if test -f "$MYSQL_CONF" && ! conffile_is_unmodified "$MYSQL_CONF" && grep -q '\<skip-bdb\>' "$MYSQL_CONF"
then
	echo "ERROR: The MySQL configuration file /etc/mysql/my.cnf has been modified and"
	echo "       contains the deprecated option 'skip-bdb'. The option MUST be removed"
	echo "       before the update can continue."
	exit 1
fi

# check for users with mailaddress but no mailhomeserver (Bug #29605)
if is_ucr_true mail/cyrus/mailbox/delete; then
	users_without_univentionMailHomeServer=$(univention-ldapsearch -xLLL '(&(mailPrimaryAddress=*)(!(univentionMailHomeServer=*)))' dn | sed -e 's/dn: //g;/^$/d')
	if [ -n "$users_without_univentionMailHomeServer" ]; then
		echo "ERROR: Detected users with an e-mail address, but without the attribute"
		echo "       univentionMailHomeServer. As the Univention Config Registry"
		echo "       variable mail/cyrus/mailbox/delete is set to true, the update will"
		printf "       be blocked, otherwise the following user mailboxes would be deleted:\n"
		printf "%s\n" "$users_without_univentionMailHomeServer"
	fi
fi

# check for possible GRUB2 partitions on non-EFI systems (Bug #32634)
eval "$(ucr shell update/grub/boot)"
if ! is_ucr_true grub/efi ; then
	if [ -z "$update_grub_boot" ] && ! is_ucr_true grub/efi ; then
		for device in $(egrep '^\s*[0-9]+' /proc/partitions | awk '{print $4}' | egrep -v "^(fd|sr|scd|dm-)" ) ; do
			# code borrowed from grub-common.postinst:
			# a) find "GRUB" within boot sector
			# b) GRUB2 uses assembler codes "63eb" (JMP) as first two bytes
			if dd if="/dev/$device" bs=512 count=1 2>/dev/null | grep -aq GRUB; then
				if [ "$(dd if=/dev/$device bs=2 count=1 2>/dev/null | od -Ax -tx2 | head -n1 | cut -d' ' -f2)" = "63eb" ] ; then
					if [ -z "$update_grub_boot" ] ; then
						update_grub_boot="/dev/$device"
					else
						unset update_grub_boot
						echo "WARNING: Cannot determine the GRUB boot device clearly."
						echo "		   After the update has been completed, please install GRUB with"
						echo "		   the following command on your boot device:"
						echo
						echo "		   grub-install <DEVICE>"
						sleep 5s
						break
					fi
				fi
			fi
		done
		if [ -n "$update_grub_boot" ] ; then
			ucr set update/grub/boot="$update_grub_boot"
		fi
	fi
	if [ -z "$(ucr get update/grub/boot)" ] ; then
		echo "WARNING: Cannot determine the GRUB boot device clearly."
		echo "		   After the update has been completed, please install GRUB with"
		echo "		   the following command on your boot device:"
		echo
		echo "		   grub-install <DEVICE>"
		sleep 5s
	fi
fi

# Pre-upgrade
preups="grub-common python-univention-directory-manager-uvmm"
$update_commands_update >&3 2>&3
for pkg in $preups; do
	if dpkg -l "$pkg" 2>&3 | grep ^ii  >&3 ; then
		echo -n "Starting pre-upgrade of $pkg: "
		$update_commands_install "$pkg" >&3 2>&3
		if [ ! $? = 0 ]; then
			echo "failed."
			echo "ERROR: Failed to upgrade $pkg."
			exit 1
		fi
		echo "done."
	fi
done

echo ""
echo "Starting update process, this may take a while."
echo "Check /var/log/univention/updater.log for more information."
date >&3
trap - EXIT

exit 0
