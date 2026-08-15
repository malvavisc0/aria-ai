# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'aboutwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QDateTime,
    QLocale,
    QMetaObject,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTime,
    QUrl,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QCursor,
    QFont,
    QFontDatabase,
    QGradient,
    QIcon,
    QImage,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)


class Ui_AboutDialog(object):
    def setupUi(self, AboutDialog):
        if not AboutDialog.objectName():
            AboutDialog.setObjectName("AboutDialog")
        AboutDialog.resize(520, 320)
        AboutDialog.setMinimumSize(QSize(400, 280))
        AboutDialog.setSizeGripEnabled(True)
        self.horizontalLayoutWidget = QWidget(AboutDialog)
        self.horizontalLayoutWidget.setObjectName("horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(9, 270, 501, 41))
        self.horizontalLayout = QHBoxLayout(self.horizontalLayoutWidget)
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.pushButton_Ok = QPushButton(self.horizontalLayoutWidget)
        self.pushButton_Ok.setObjectName("pushButton_Ok")

        self.horizontalLayout.addWidget(self.pushButton_Ok)

        self.formLayoutWidget = QWidget(AboutDialog)
        self.formLayoutWidget.setObjectName("formLayoutWidget")
        self.formLayoutWidget.setGeometry(QRect(10, 20, 501, 71))
        self.formLayout = QFormLayout(self.formLayoutWidget)
        self.formLayout.setObjectName("formLayout")
        self.formLayout.setContentsMargins(0, 0, 0, 0)
        self.label_2 = QLabel(self.formLayoutWidget)
        self.label_2.setObjectName("label_2")
        font = QFont()
        font.setPointSize(18)
        self.label_2.setFont(font)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.label_2)

        self.label_Version = QLabel(self.formLayoutWidget)
        self.label_Version.setObjectName("label_Version")
        font1 = QFont()
        font1.setPointSize(16)
        self.label_Version.setFont(font1)

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.label_Version)

        self.label_3 = QLabel(self.formLayoutWidget)
        self.label_3.setObjectName("label_3")
        self.label_3.setStyleSheet("color: rgb(61, 56, 70)")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_3)

        self.label = QLabel(self.formLayoutWidget)
        self.label.setObjectName("label")
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setOpenExternalLinks(True)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.label)

        self.verticalLayoutWidget = QWidget(AboutDialog)
        self.verticalLayoutWidget.setObjectName("verticalLayoutWidget")
        self.verticalLayoutWidget.setGeometry(QRect(9, 100, 501, 150))
        self.verticalLayout = QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.label_Tagline = QLabel(self.verticalLayoutWidget)
        self.label_Tagline.setObjectName("label_Tagline")
        font2 = QFont()
        font2.setPointSize(11)
        font2.setItalic(True)
        self.label_Tagline.setFont(font2)
        self.label_Tagline.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_Tagline)

        self.label_Copyright = QLabel(self.verticalLayoutWidget)
        self.label_Copyright.setObjectName("label_Copyright")
        self.label_Copyright.setStyleSheet("color: rgb(61, 56, 70);")
        self.label_Copyright.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_Copyright)

        self.label_Details = QLabel(self.verticalLayoutWidget)
        self.label_Details.setObjectName("label_Details")
        self.label_Details.setTextFormat(Qt.TextFormat.RichText)
        self.label_Details.setOpenExternalLinks(True)
        self.label_Details.setWordWrap(True)

        self.verticalLayout.addWidget(self.label_Details)

        self.retranslateUi(AboutDialog)

        QMetaObject.connectSlotsByName(AboutDialog)

    # setupUi

    def retranslateUi(self, AboutDialog):
        AboutDialog.setWindowTitle(
            QCoreApplication.translate("AboutDialog", "About", None)
        )
        self.pushButton_Ok.setText(
            QCoreApplication.translate("AboutDialog", "OK", None)
        )
        self.label_2.setText(QCoreApplication.translate("AboutDialog", "Aria", None))
        self.label_Version.setText(QCoreApplication.translate("AboutDialog", "v", None))
        self.label_3.setText(QCoreApplication.translate("AboutDialog", "Source", None))
        self.label.setText(
            QCoreApplication.translate(
                "AboutDialog",
                '<a href="https://github.com/malvavisc0/aria-ai">GitHub Repository</a>',
                None,
            )
        )
        self.label_Tagline.setText(
            QCoreApplication.translate(
                "AboutDialog",
                "AI Assistant with web UI, CLI management, and local LLM support",
                None,
            )
        )
        self.label_Copyright.setText(
            QCoreApplication.translate(
                "AboutDialog",
                "Built for local-first workflows with multi-agent orchestration.",
                None,
            )
        )
        self.label_Details.setText(
            QCoreApplication.translate(
                "AboutDialog",
                "<b>Stack</b>: Chainlit, LlamaIndex, PySide6<br/><b>License</b>: See repository for project details",
                None,
            )
        )

    # retranslateUi
