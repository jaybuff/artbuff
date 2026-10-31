# "Send to Frame TV" Apple Shortcut

Share an image on your iPhone or iPad and it appears on the Frame TV. The shortcut posts the image to ArtBuff's `POST /api/send-image` and shows the reply as a notification.

Your device has to be able to reach ArtBuff, so this only works on your home network.

## Install it

Get `Send to Frame TV.shortcut` from the [latest release](https://github.com/jaybuff/artbuff/releases/latest), or have someone AirDrop it to you, and open it. When asked, enter your ArtBuff send-image URL, such as `http://artbuff.jaybuff.com/api/send-image`.

The first time it runs, allow it to connect to ArtBuff and, if asked, to your local network.

## Use it

Long-press an image in Safari, or open one in Photos, then tap **Share → Send to Frame TV**. You can also share a link that points directly at an image: the shortcut downloads it on your device and sends the bytes. Sharing a web page from Safari's toolbar sends the page rather than an image on it, so ArtBuff replies that it isn't a usable image.

Send one image at a time.

## Build it

On a Mac signed in to iCloud (signing goes through Apple):

```sh
python3 scripts/build_shortcut.py
```

This writes a signed `dist/Send to Frame TV.shortcut` that anyone can import. `--url` changes the address offered as the default on import. `--no-sign` works anywhere with Python: it writes `dist/Send to Frame TV unsigned.shortcut`, which Shortcuts won't import, and prints the `shortcuts sign` command to run on a signed-in Mac. To publish it:

```sh
gh release create <tag> 'dist/Send to Frame TV.shortcut'
```

GitHub replaces the spaces in attachment names with dots, and an imported shortcut is named after its file, so rename the download to `Send to Frame TV.shortcut` before opening it, or AirDrop the original.

## Replies

| Status | `ok` | `message` means |
|---|---|---|
| 200 | `true` | The image is on the TV |
| 400 | `false` | No image was sent, or it couldn't be read |
| 413 | `false` | The image is over 50 MB |
| 502 | `false` | The image was saved (`"saved": true`), but the TV didn't take it. Display it later from History |

To test the endpoint without the shortcut:

```sh
curl --data-binary @photo.jpg -H 'Content-Type: application/octet-stream' \
  'http://artbuff.jaybuff.com/api/send-image?title=My%20photo'
```
