import { render } from "preact";
import { App } from "./ui/App";
import "./ui/styles/styles.css";

const root = document.getElementById("root");

if (root) {
  render(<App />, root);
}
