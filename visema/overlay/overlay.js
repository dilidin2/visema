/**
 * Visema Overlay Script
 * Receives WebSocket events from the FastAPI server and renders GIFs or plays audio.
 * Designed for OBS Browser Source (embedded Chromium) — no external dependencies.
 */

(function () {
    "use strict";

    var container = document.getElementById("overlay-container");
    var ws = null;
    var reconnectDelay = 1000;
    var audioDone = null; // deferred to signal queue worker when audio finishes
    var gifDone = null; // deferred to signal queue worker when GIF is fully removed

    // ── WebSocket connection ────────────────────────────

    function connect() {
        var proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        var url = proto + "//" + window.location.host + "/ws";

        ws = new WebSocket(url);

        ws.onopen = function () {
            console.log("[visema] WebSocket connected");
            reconnectDelay = 1000;
        };

        ws.onclose = function () {
            console.log("[visema] WebSocket disconnected, reconnecting...");
            resolveAudioDone(); // unblock any pending audio
            resolveGifDone(); // unblock any pending GIF
            setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 10000);
        };

        ws.onerror = function (e) {
            console.error("[visema] WebSocket error", e);
        };

        ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                handleMessage(data);
            } catch (err) {
                console.error("[visema] Failed to parse message:", err);
            }
        };
    }

    // ── Message handler ─────────────────────────────────

    function handleMessage(msg) {
        if (!msg || !msg.type) return;

        if (msg.type === "gif") {
            showGif(msg.url, msg.duration || 8);
        } else if (msg.type === "audio") {
            playAudio(msg.src, msg.volume || 1.0);
        }
    }

    // ── GIF display ─────────────────────────────────────

    function showGif(url, durationSeconds) {
        var img = document.createElement("img");
        img.className = "gif-image";
        img.src = url;

        // Size: use config size_percent or default 40%
        var sizePercent = window.visemaSizePercent || 40;
        img.style.width = sizePercent + "%";

        container.appendChild(img);

        // Fade in
        requestAnimationFrame(function () {
            img.classList.add("visible");
        });

        // Fade out and remove after duration
        var durationMs = durationSeconds * 1000;
        setTimeout(function () {
            img.classList.remove("visible");

            // Wait for fade-out transition, then remove
            setTimeout(function () {
                if (img.parentNode) {
                    img.parentNode.removeChild(img);
                }
                // Notify queue worker that GIF is fully removed
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ ack: "gif_done" }));
                }
            }, 500);
        }, durationMs);
    }

    // ── Audio playback ──────────────────────────────────

    function playAudio(src, volume) {
        // Resolve relative path to full URL
        if (src.indexOf("://") === -1) {
            src = window.location.origin + src;
        }

        var audio = new Audio(src);
        audio.volume = Math.min(Math.max(volume, 0.0), 1.0);

        // Create a deferred so the queue worker can await completion
        var deferred = {};
        audioDone = deferred;

        audio.addEventListener("canplaythrough", function () {
            audio.play().catch(function (err) {
                console.error("[visema] Audio playback failed:", err);
                resolveAudioDone();
            });
        });

        audio.addEventListener("error", function () {
            console.error("[visema] Audio load error for:", src);
            resolveAudioDone();
        });

        audio.addEventListener("ended", function () {
            resolveAudioDone();
        });

        // Timeout fallback: if audio doesn't end within 30s, unblock
        setTimeout(function () {
            if (audioDone === deferred) {
                console.warn("[visema] Audio timeout for:", src);
                resolveAudioDone();
            }
        }, 30000);

        // Send ack back so queue knows audio is playing
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ ack: "audio_playing" }));
        }
    }

    function resolveAudioDone() {
        if (audioDone) {
            audioDone._resolved = true;
            if (audioDone._callback) {
                audioDone._callback();
            }
            audioDone = null;
        }
    }

    function resolveGifDone() {
        if (gifDone) {
            gifDone._resolved = true;
            if (gifDone._callback) {
                gifDone._callback();
            }
            gifDone = null;
        }
    }

    // ── Position helper ─────────────────────────────────

    function setPosition(position) {
        container.className = "";
        if (position) {
            container.classList.add("position-" + position);
        }
    }

    // ── Expose config setters (called from server or manually) ──

    window.visemaSetSize = function (percent) {
        window.visemaSizePercent = percent;
    };

    window.visemaSetPosition = setPosition;

    // ── Start ───────────────────────────────────────────

    connect();
})();
