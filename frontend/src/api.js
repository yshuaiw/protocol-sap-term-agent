export async function api(path, method = 'GET', data) {
  const options = {method};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(data);
  }
  const response = await fetch('/api' + path, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({detail: response.statusText}));
    throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
  }
  return response.json();
}
