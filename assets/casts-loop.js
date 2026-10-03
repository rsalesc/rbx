/* Creates an asciinema-player that holds its final frame before looping.
 *
 * Every cast in the docs goes through here: the `asciinema()` macro in
 * `main.py` for pages, and `docs/templates/home.html` for the landing page.
 * They used to each call `AsciinemaPlayer.create` themselves, which is how the
 * home page kept restarting instantly after the macro learned to pause.
 *
 * The pause cannot live in the cast file. A trailing idle gap there is idle
 * time like any other: the player clamps it to `idleTimeLimit` and then
 * divides it by `speed`, so a recorded "3 second hold" plays for one second,
 * or half of one on a `speed=2` embed. A timer here is wall-clock, and so is
 * the same three seconds at any playback rate.
 */
window.rbxCast = function (src, elementId, options, pauseMs) {
  var element = document.getElementById(elementId);
  if (!element || typeof AsciinemaPlayer === 'undefined') {
    return null;
  }

  var opts = Object.assign(
    { autoPlay: true, idleTimeLimit: 1, fit: 'width' },
    options || {}
  );
  // Not overridable: the player's own `loop` restarts on the tick after the
  // last frame is drawn, which is exactly what the pause below exists to stop.
  opts.loop = false;

  var player = AsciinemaPlayer.create(src, element, opts);
  var delay = pauseMs === undefined ? 3000 : pauseMs;
  var pending = null;

  player.addEventListener('ended', function () {
    // `ended` can fire again while a restart is queued (a seek to the end, a
    // double-fire on some browsers); one pending restart is enough.
    if (pending !== null) {
      return;
    }
    pending = setTimeout(function () {
      pending = null;
      player.seek(0);
      player.play();
    }, delay);
  });

  return player;
};
