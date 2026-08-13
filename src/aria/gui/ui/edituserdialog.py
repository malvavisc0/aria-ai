# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'edituserdialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import QCoreApplication, QMetaObject, QRect, QSize
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QWidget,
)


class Ui_EditUserDialog(object):
    def setupUi(self, EditUserDialog):
        if not EditUserDialog.objectName():
            EditUserDialog.setObjectName("EditUserDialog")
        EditUserDialog.resize(400, 200)
        EditUserDialog.setMinimumSize(QSize(350, 180))
        self.formLayoutWidget = QWidget(EditUserDialog)
        self.formLayoutWidget.setObjectName("formLayoutWidget")
        self.formLayoutWidget.setGeometry(QRect(10, 10, 381, 131))
        self.formLayout = QFormLayout(self.formLayoutWidget)
        self.formLayout.setObjectName("formLayout")
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.label_Name = QLabel(self.formLayoutWidget)
        self.label_Name.setObjectName("label_Name")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label_Name)

        self.lineEdit_Name = QLineEdit(self.formLayoutWidget)
        self.lineEdit_Name.setObjectName("lineEdit_Name")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.lineEdit_Name)

        self.label_Password = QLabel(self.formLayoutWidget)
        self.label_Password.setObjectName("label_Password")

        self.formLayout.setWidget(
            1, QFormLayout.ItemRole.LabelRole, self.label_Password
        )

        self.lineEdit_Password = QLineEdit(self.formLayoutWidget)
        self.lineEdit_Password.setObjectName("lineEdit_Password")
        self.lineEdit_Password.setEchoMode(QLineEdit.EchoMode.Password)

        self.formLayout.setWidget(
            1, QFormLayout.ItemRole.FieldRole, self.lineEdit_Password
        )

        self.label_PasswordHintText = QLabel(self.formLayoutWidget)
        self.label_PasswordHintText.setObjectName("label_PasswordHintText")
        self.label_PasswordHintText.setStyleSheet(
            "color: rgb(104, 104, 104); font-style: italic;"
        )

        self.formLayout.setWidget(
            2, QFormLayout.ItemRole.FieldRole, self.label_PasswordHintText
        )

        self.horizontalLayoutWidget = QWidget(EditUserDialog)
        self.horizontalLayoutWidget.setObjectName("horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(10, 150, 381, 41))
        self.horizontalLayout = QHBoxLayout(self.horizontalLayoutWidget)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.pushButton_Save = QPushButton(self.horizontalLayoutWidget)
        self.pushButton_Save.setObjectName("pushButton_Save")

        self.horizontalLayout.addWidget(self.pushButton_Save)

        self.pushButton_Cancel = QPushButton(self.horizontalLayoutWidget)
        self.pushButton_Cancel.setObjectName("pushButton_Cancel")

        self.horizontalLayout.addWidget(self.pushButton_Cancel)

        self.retranslateUi(EditUserDialog)

        QMetaObject.connectSlotsByName(EditUserDialog)

    # setupUi

    def retranslateUi(self, EditUserDialog):
        EditUserDialog.setWindowTitle(
            QCoreApplication.translate("EditUserDialog", "Edit User", None)
        )
        self.label_Name.setText(
            QCoreApplication.translate("EditUserDialog", "Name:", None)
        )
        self.label_Password.setText(
            QCoreApplication.translate("EditUserDialog", "Password:", None)
        )
        self.label_PasswordHintText.setText(
            QCoreApplication.translate(
                "EditUserDialog", "Leave empty to keep current password", None
            )
        )
        self.pushButton_Save.setText(
            QCoreApplication.translate("EditUserDialog", "Save", None)
        )
        self.pushButton_Cancel.setText(
            QCoreApplication.translate("EditUserDialog", "Cancel", None)
        )

    # retranslateUi
