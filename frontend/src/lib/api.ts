import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
});

export async function verifyIdentity(cccdFile: File, selfieFile: File) {
  const formData = new FormData();
  formData.append('cccd_image', cccdFile);
  formData.append('selfie_image', selfieFile);

  const response = await api.post('/verify', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

export async function getResult(requestId: string) {
  const response = await api.get(`/results/${requestId}`);
  return response.data;
}

export async function healthCheck() {
  const response = await api.get('/health');
  return response.data;
}

export default api;
