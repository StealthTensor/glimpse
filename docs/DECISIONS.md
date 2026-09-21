# Decisions

## D001 --- Project name

Glimpse.

## D002 --- RGB camera

Current hardware exposes one image stream at `/dev/video0` and a
metadata node at `/dev/video1`. No separate IR camera endpoint is
visible.

## D003 --- Password fallback

Mandatory for initial releases.

## D004 --- PAM architecture

PAM adapter remains thin; recognition lives outside PAM.

## D005 --- Howdy

Howdy is an initial integration/backend candidate, not the core
architectural dependency.

## D006 --- Network

No network authentication API. Use Unix-domain IPC.

## D007 --- Local-first

No cloud biometric processing.
