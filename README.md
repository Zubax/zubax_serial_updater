# Zubax Serial Updater

Simple cross-platform GUI application to update MCU firmware via serial port.

Put the binaries into the current directory, making sure that their extension is `.bin`.
When started, the application will pick all available `*.bin` files from its local directory/package,
making them available for choice from a drop-down list.

## Linux

Python dependencies:

* Python 3.x (recommended) or 2.7
* `serial`
* `tkinter`

The application should be used as-is, no installation is required.

## Windows

Build-time Python dependencies:

* Python 3.x
* `serial`
* `tkinter`
* `cx_Freeze`

Build instructions:

* Put the binary into this directory, its extension must be `.bin`
* Execute `python setup.py bdist_msi`
* Collect the resulting `.msi` archive
