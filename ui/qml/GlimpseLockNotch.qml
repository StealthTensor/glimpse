import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: notchRoot
    width: 220
    height: 190
    anchors.top: parent.top
    anchors.horizontalCenter: parent.horizontalCenter
    z: 99999

    property bool uiVisible: false
    property bool isSuccess: false

    property real bodyWidth: 160.0
    property real expandedHeight: 160.0
    property real topRadius: 18.0
    property real bottomRadius: 40.0
    property real currentH: 0.0
    property real shakeOffset: 0.0

    property string state: "idle" // idle, scanning, success, failure, collapsing
    property int frameIdx: 1
    property int maxFrames: 73
    property string assetsDir: "file:///home/stealthtensor/EX/pro/Glimpse/assets/"

    onUiVisibleChanged: {
        if (uiVisible) {
            startScan();
        } else {
            collapse();
        }
    }

    function startScan() {
        isSuccess = false;
        state = "scanning";
        frameIdx = 1;
        shakeOffset = 0.0;
        collapseAnim.stop();
        expandAnim.stop();
        expandAnim.from = currentH;
        expandAnim.to = expandedHeight;
        expandAnim.start();
    }

    function triggerSuccess() {
        isSuccess = true;
        state = "success";
        frameIdx = 1;
        frameTimer.start();
        successHoldTimer.start();
    }

    function triggerFailure() {
        isSuccess = false;
        state = "failure";
        frameIdx = 1;
        failureShakeAnim.start();
        failureHoldTimer.start();
    }

    function collapse() {
        state = "collapsing";
        frameTimer.stop();
        expandAnim.stop();
        collapseAnim.stop();
        collapseAnim.from = currentH;
        collapseAnim.to = 0.0;
        collapseAnim.start();
    }

    onCurrentHChanged: notchCanvas.requestPaint()
    onShakeOffsetChanged: notchCanvas.requestPaint()

    NumberAnimation {
        id: expandAnim
        target: notchRoot
        property: "currentH"
        duration: 440
        easing.type: Easing.OutCubic
    }

    NumberAnimation {
        id: collapseAnim
        target: notchRoot
        property: "currentH"
        duration: 320
        easing.type: Easing.OutCubic
        onFinished: {
            notchRoot.state = "idle";
            if (notchRoot.isSuccess) {
                Qt.quit();
            }
        }
    }

    SequentialAnimation {
        id: failureShakeAnim
        NumberAnimation { target: notchRoot; property: "shakeOffset"; to: -12; duration: 50; easing.type: Easing.OutQuad }
        NumberAnimation { target: notchRoot; property: "shakeOffset"; to: 12; duration: 80; easing.type: Easing.InOutQuad }
        NumberAnimation { target: notchRoot; property: "shakeOffset"; to: -8; duration: 70; easing.type: Easing.InOutQuad }
        NumberAnimation { target: notchRoot; property: "shakeOffset"; to: 8; duration: 60; easing.type: Easing.InOutQuad }
        NumberAnimation { target: notchRoot; property: "shakeOffset"; to: 0; duration: 50; easing.type: Easing.OutQuad }
    }

    Timer {
        id: frameTimer
        interval: 14
        repeat: true
        running: false
        onTriggered: {
            if (notchRoot.frameIdx < notchRoot.maxFrames) {
                notchRoot.frameIdx += 1;
            } else {
                stop();
            }
        }
    }

    Timer {
        id: successHoldTimer
        interval: 850
        repeat: false
        onTriggered: notchRoot.collapse()
    }

    Timer {
        id: failureHoldTimer
        interval: 1400
        repeat: false
        onTriggered: notchRoot.collapse()
    }

    Canvas {
        id: notchCanvas
        anchors.fill: parent
        visible: notchRoot.currentH > 2.0
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();

            var cx = (width / 2.0) + notchRoot.shakeOffset;
            var y = 0.0;
            var h = notchRoot.currentH;

            var currentBodyW = notchRoot.bodyWidth;
            if (h < 55.0) {
                currentBodyW = notchRoot.bodyWidth * Math.pow(h / 55.0, 0.55);
            }

            var botR = Math.min(notchRoot.bottomRadius, h * 0.46, (currentBodyW / 2.0) * 0.9);
            var topR = Math.min(notchRoot.topRadius, h * 0.30, (currentBodyW / 2.0) * 0.5);
            var totalW = currentBodyW + 2.0 * topR;
            var x = cx - totalW / 2.0;

            // Build notch path attached flush to top (y=0)
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.quadraticCurveTo(x + topR, y, x + topR, y + topR);
            ctx.lineTo(x + topR, y + h - botR);
            ctx.quadraticCurveTo(x + topR, y + h, x + topR + botR, y + h);
            ctx.lineTo(x + totalW - topR - botR, y + h);
            ctx.quadraticCurveTo(x + totalW - topR, y + h, x + totalW - topR, y + h - botR);
            ctx.lineTo(x + totalW - topR, y + topR);
            ctx.quadraticCurveTo(x + totalW - topR, y, x + totalW, y);
            ctx.lineTo(x, y);
            ctx.closePath();

            // Ambient shadow
            ctx.shadowColor = "rgba(0, 0, 0, 0.45)";
            ctx.shadowBlur = 10;
            ctx.shadowOffsetY = 4;

            // Pure OLED Black Body (#000000)
            ctx.fillStyle = "#000000";
            ctx.fill();
        }
    }

    // Center FaceID Icon / Frame Animation
    Item {
        id: glyphContainer
        width: 110
        height: 110
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.horizontalCenterOffset: notchRoot.shakeOffset
        y: Math.max(-10, (notchRoot.currentH * 0.5) - (height * 0.5) - 1.0)
        visible: notchRoot.currentH > 60.0
        opacity: Math.min(1.0, (notchRoot.currentH - 60.0) / 45.0)

        Image {
            id: staticGlyph
            anchors.fill: parent
            source: notchRoot.assetsDir + "unlockstatic.png"
            fillMode: Image.PreserveAspectFit
            visible: notchRoot.state === "scanning" || notchRoot.state === "idle"
            smooth: true
        }

        Image {
            id: animatedGlyph
            anchors.fill: parent
            source: {
                var prefix = notchRoot.state === "failure" ? "frames_failure/frame_" : "frames_success/frame_";
                var numStr = ("000" + notchRoot.frameIdx).slice(-3);
                return notchRoot.assetsDir + prefix + numStr + ".png";
            }
            fillMode: Image.PreserveAspectFit
            visible: notchRoot.state === "success" || notchRoot.state === "failure"
            smooth: true
        }
    }

    Connections {
        target: typeof authenticator !== "undefined" ? authenticator : null
        function onFailed(kind) {
            if (kind === 0) {
                notchRoot.triggerFailure();
            }
        }
        function onSucceeded() {
            notchRoot.triggerSuccess();
        }
    }
}
