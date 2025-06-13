const e = React.createElement;

function App() {
  return e('div', null, 'Hello from React');
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(e(App));
