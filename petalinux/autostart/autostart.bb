SUMMARY = "Autostart script"
SECTION = "PETALINUX/apps"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://autostart.service file://autostart"

S = "${WORKDIR}"

FILESEXTRAPATHS:prepend := "${THISDIR}/files:"

inherit update-rc.d systemd

INITSCRIPT_NAME = "autostart"
INITSCRIPT_PARAMS = "start 99 S ."

SYSTEMD_PACKAGES = "${PN}"
SYSTEMD_SERVICE:${PN} = "autostart.service"
SYSTEMD_AUTO_ENABLE:${PN} = "enable"

do_install() {
        install -d ${D}${sysconfdir}/init.d/
	install -m 0755 ${WORKDIR}/autostart ${D}${sysconfdir}/init.d/
        install -d ${D}${bindir}
        install -m 0755 ${WORKDIR}/autostart ${D}${bindir}
	install -d ${D}${systemd_system_unitdir}
	install -m 0644 ${WORKDIR}/autostart.service ${D}${systemd_system_unitdir}
}

RDEPENDS_${PN}:append += "bash"
