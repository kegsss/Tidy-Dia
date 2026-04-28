// keyboard accelerators (placeholder)
document.addEventListener("keydown", (e) => {
  if (e.key === "/") {
    const search = document.querySelector('input[type=search]');
    if (search) { e.preventDefault(); search.focus(); }
  }
});
