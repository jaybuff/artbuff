# "Send to Frame TV" Apple Shortcut

Share an image on your iPhone or iPad and it appears on the Frame TV. The shortcut posts the image to ArtBuff's `POST /api/send-image` and shows the reply as a notification.

Your device has to be able to reach ArtBuff, so this only works on your home network.

## Build it

In the Shortcuts app, create a shortcut named **Send to Frame TV**:

1. Open the shortcut's details (the **ⓘ** or settings button) and turn on **Show in Share Sheet**.
2. At the top of the shortcut, tap the input types and leave only **Images** selected. If there's an "If there's no input" option, choose **Stop and Respond**.
3. Add **Get Contents of URL**. Set the URL to `http://artbuff.jaybuff.com/api/send-image`, or your own ArtBuff address, then expand **Show More**:
   - **Method:** `POST`
   - **Request Body:** `File`
   - **File:** the **Shortcut Input** variable
4. Add **Get Dictionary Value**. Set it to get the value for the key `message` in **Contents of URL**.
5. Add **Show Notification** and set its text to **Dictionary Value**.

The first time it runs, allow it to connect to ArtBuff and, if asked, to your local network.

## Use it

Long-press an image in Safari, or open one in Photos, then tap **Share → Send to Frame TV**. Share the image itself: the toolbar Share button in Safari shares the page, not an image.

Send one image at a time.

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
