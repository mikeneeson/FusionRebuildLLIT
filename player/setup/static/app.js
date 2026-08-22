/* Setup screen behaviour.
 *
 * The only input at a studio is a 2.4GHz air remote that presents as a plain
 * keyboard: arrow keys and Enter, no mouse and no pointer. So everything here
 * is driven by moving focus between elements, and clicking is just a bonus for
 * whoever opens this on a phone. */

'use strict';

var STEPS = 4;
var step = 0;
var picked = { host: '', port: '', path: '' };
var startingUrl = null;
var scanTimer = null;
var touched = false;      // has anyone actually pressed a key yet

function $(id) { return document.getElementById(id); }
function sections() { return document.querySelectorAll('main .step'); }

/* ------------------------------------------------------------ moving around */

function focusables() {
  var active = document.querySelector('main .step[data-step="' + step + '"]');
  return Array.prototype.slice.call(active.querySelectorAll('.focusable'))
    .filter(function (el) { return !el.disabled && el.offsetParent !== null; });
}

function moveFocus(by) {
  var items = focusables();
  if (!items.length) { return; }
  var at = items.indexOf(document.activeElement);
  var next = at < 0 ? 0 : (at + by + items.length) % items.length;
  items[next].focus();
  if (items[next].scrollIntoView) {
    items[next].scrollIntoView({ block: 'nearest' });
  }
}

function show(which) {
  step = Math.max(0, Math.min(STEPS - 1, which));
  sections().forEach(function (el) {
    el.hidden = Number(el.dataset.step) !== step;
  });
  document.querySelectorAll('.steps span').forEach(function (el) {
    var n = Number(el.dataset.step);
    el.className = n === step ? 'on' : (n < step ? 'done' : '');
  });
  if (step === STEPS - 1) {
    $('assembled').textContent = assembled();
    $('result').textContent = '';
    $('result').className = 'result';
  }
  updatePreview();
  var first = focusables()[0];
  if (first) { first.focus(); }
}

/* --------------------------------------------------------- building the URL */

function assembled() {
  var host = picked.host || $('hostInput').value.trim();
  var port = (picked.port || $('portInput').value).trim();
  var path = (picked.path || $('pathInput').value).trim().replace(/^\/+|\/+$/g, '');
  if (!host) { return ''; }
  return 'http://' + host + ':' + (port || '8888') + '/' + (path ? path + '/' : '');
}

function updatePreview() {
  var url = assembled();
  $('preview').innerHTML = url
    ? '<em>Will load</em>  ' + url.replace(/[&<>]/g, '')
    : '';
}

/* -------------------------------------------------------------- the scanning */

function renderDevices(data) {
  var list = $('deviceList');
  var focusedIp = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.ip : null;

  list.innerHTML = '';
  data.devices.forEach(function (device) {
    var li = document.createElement('li');
    li.className = 'focusable' + (device.synology ? ' likely' : '');
    li.tabIndex = 0;
    li.dataset.ip = device.ip;

    var ip = document.createElement('span');
    ip.className = 'ip';
    ip.textContent = device.ip;

    var name = document.createElement('span');
    name.className = 'name';
    name.textContent = device.name || device.reason || '';

    var why = document.createElement('span');
    why.className = 'badge';
    why.textContent = device.synology ? 'Synology' : (device.reason || '');

    li.appendChild(ip);
    li.appendChild(name);
    li.appendChild(why);
    li.addEventListener('click', function () { chooseHost(device.ip); });
    list.appendChild(li);
  });

  // Keep the highlight where it was across a redraw. Until somebody touches a
  // key, park it on the most likely device instead, so that on a TV the whole
  // first step is one press of Enter.
  if (focusedIp) {
    var same = list.querySelector('[data-ip="' + focusedIp + '"]');
    if (same) { same.focus(); }
  } else if (step === 0 && !touched && list.firstChild) {
    list.firstChild.focus();
  }

  if (data.running) {
    $('scanStatus').textContent = data.devices.length
      ? 'Still looking. Found ' + data.devices.length + ' so far.'
      : 'Looking for devices on the network…';
  } else if (data.error) {
    $('scanStatus').textContent = 'The scan failed: ' + data.error;
  } else if (!data.devices.length) {
    $('scanStatus').textContent =
      'Nothing found on ' + (data.network || 'this network') + '. Type the address below.';
  } else {
    $('scanStatus').textContent =
      'Found ' + data.devices.length + ' on ' + data.network + '. Top one is the most likely.';
  }
}

function pollScan() {
  fetch('/api/scan').then(function (r) { return r.json(); }).then(function (data) {
    renderDevices(data);
    if (!data.running) { clearInterval(scanTimer); scanTimer = null; }
  }).catch(function () { /* the page is still usable without the list */ });
}

function startScan() {
  $('scanStatus').textContent = 'Looking for devices on the network…';
  $('deviceList').innerHTML = '';
  fetch('/api/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ port: $('portInput').value || 8888 })
  }).catch(function () {});
  if (!scanTimer) { scanTimer = setInterval(pollScan, 1000); }
}

/* -------------------------------------------------------------- the sequence */

function chooseHost(host) {
  if (!host) { return; }
  picked.host = host.trim();
  $('hostInput').value = picked.host;
  show(1);
}

function save() {
  var result = $('result');
  result.className = 'result busy';
  result.textContent = 'Loading the page to check it works…';
  $('saveBtn').disabled = true;

  fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      host: picked.host || $('hostInput').value,
      port: $('portInput').value,
      path: $('pathInput').value
    })
  }).then(function (r) { return r.json(); }).then(function (data) {
    $('saveBtn').disabled = false;
    if (data.ok) {
      result.className = 'result good';
      result.textContent = 'That page works' +
        (data.title ? ' (' + data.title + ')' : '') + '. Saved. Loading it now…';
      setTimeout(function () { window.location.href = data.url; }, 1200);
    } else {
      result.className = 'result bad';
      result.textContent = data.error + ' Nothing has been saved.';
    }
  }).catch(function (error) {
    $('saveBtn').disabled = false;
    result.className = 'result bad';
    result.textContent = 'The player could not be reached: ' + error;
  });
}

/* ------------------------------------------------------------- the keyboard */

function typingIn(el) {
  return el && el.tagName === 'INPUT';
}

document.addEventListener('keydown', function (event) {
  var target = event.target;
  touched = true;

  if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(1); return; }
  if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(-1); return; }

  // Left and right belong to the caret when someone is typing an address.
  if (!typingIn(target)) {
    if (event.key === 'ArrowRight') { event.preventDefault(); moveFocus(1); return; }
    if (event.key === 'ArrowLeft') { event.preventDefault(); moveFocus(-1); return; }
  }

  if (event.key === 'Enter') {
    if (target.dataset && target.dataset.ip) { event.preventDefault(); chooseHost(target.dataset.ip); return; }
    if (target === $('hostInput')) { event.preventDefault(); chooseHost(target.value); return; }
    if (target === $('portInput')) { event.preventDefault(); show(2); return; }
    if (target === $('pathInput')) { event.preventDefault(); show(3); return; }
    return;                                  // buttons handle their own Enter
  }

  // Backspace is the back button, unless it is deleting a character.
  if ((event.key === 'Backspace' && !typingIn(target)) || event.key === 'Escape') {
    event.preventDefault();
    if (step > 0) { show(step - 1); }
  }
});

/* ------------------------------------------------------------------ start up */

function chip(container, label, value, input) {
  var button = document.createElement('button');
  button.className = 'focusable';
  button.textContent = label;
  button.addEventListener('click', function () {
    input.value = value;
    updatePreview();
    input.focus();
  });
  container.appendChild(button);
}

function boot() {
  fetch('/api/state').then(function (r) { return r.json(); }).then(function (data) {
    $('ownUrl').textContent = 'http://' + data.own_ip + ':7777';
    $('version').textContent = data.version ? 'v' + data.version : '';
    if (data.theme === 'light') { document.documentElement.dataset.theme = 'light'; }
    $('portInput').value = data.default_port;
    $('pathInput').value = data.default_path;
    startingUrl = data.url;
    updatePreview();
    startScan();
  }).catch(function () {
    $('scanStatus').textContent = 'The setup service is not answering.';
  });

  ['8888', '80', '5000', '5001'].forEach(function (p) {
    chip($('portChips'), p, p, $('portInput'));
  });
  chip($('pathChips'), 'control', 'control', $('pathInput'));
  chip($('pathChips'), 'no folder', '', $('pathInput'));

  $('rescan').addEventListener('click', startScan);
  $('saveBtn').addEventListener('click', save);
  $('backBtn').addEventListener('click', function () { show(2); });
  ['hostInput', 'portInput', 'pathInput'].forEach(function (id) {
    $(id).addEventListener('input', function () { touched = true; updatePreview(); });
  });

  // If somebody saves a URL from their phone, the TV should follow them there
  // rather than sitting on this screen waiting for a reboot.
  setInterval(function () {
    fetch('/api/state').then(function (r) { return r.json(); }).then(function (data) {
      if (startingUrl !== null && data.url && data.url !== startingUrl) {
        window.location.href = data.url;
      }
    }).catch(function () {});
  }, 2000);

  show(0);
}

boot();
