// ==UserScript==
// @name     MultiSubmit
// @version  1
// @grant    none
// @match    https://cytu.be/*
// ==/UserScript==

function add(current, rest) {
  console.log(current)
  let title = current[0]
  const url = current[1] || title
  if (title == url) title = '';
  const tm = 1000
  const inputUrl = document.querySelector("#mediaurl")
  const queueBut = document.querySelector("#queue_end")
  function wait() {
    setTimeout(add, tm, rest[0], rest.slice(1))
  }
  function queue() {
    console.log("queue")
    queueBut.click()
    setTimeout(wait, tm*2)
  }
  function setTitle() {
    const inputTitle = document.querySelector("#addfromurl-title-val")
    console.log("setTitle")
    if (inputTitle) inputTitle.value = title
    setTimeout(queue, tm)
  }
  function keyUp() {
    console.log("keyUp")
    inputUrl.dispatchEvent(new Event("keyup"))
    setTimeout(setTitle, tm)
  }
  function setUrl() {
    console.log("setUrl")
    inputUrl.value = url
    setTimeout(keyUp, tm)
  }
  setUrl()
}

function process(dataEl) {
  const dataText = dataEl.value;
  console.log(dataText)
  const data = dataText.split("\n").map(l => l.split(";"))
  add(data[0], data.slice(1))
}

function setup() {
  if (document.getElementById("submit-all") != null) return;

  const data = document.createElement("textarea")
  data.id = "submit-all"
  data.style.resize = "none"
  data.cols = 75
  data.rows = 16
  const br = document.createElement("br")
  const button = document.createElement("button")
  button.innerText = "Submit all"
  button.onclick = () => process(data)
	button.classList.add("btn", "btn-sm", "btn-default")
  const lp = document.querySelector("#leftpane-inner")
  lp.appendChild(data)
  lp.appendChild(br)
  lp.appendChild(button)
}

const setupButton = document.createElement("button")
document.querySelector("#leftcontrols").appendChild(setupButton)
setupButton.onclick = setup
setupButton.innerText = "Setup submissions"
setupButton.classList.add("btn", "btn-sm", "btn-default")