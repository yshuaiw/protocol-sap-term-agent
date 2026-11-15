export const projectPath = p => `/projects/${p.id}`;
export const downloadPath = (p, suffix) => '/api' + projectPath(p) + suffix;
