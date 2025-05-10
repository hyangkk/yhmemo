import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyBcVp1C-heBQswmnFp5ktYgGrWULr8Gttk",
  authDomain: "memo-c082c.firebaseapp.com",
  projectId: "memo-c082c",
  storageBucket: "memo-c082c.appspot.com",
  messagingSenderId: "707834680909",
  appId: "1:707834680909:web:0f3139624fa2a21431ee04",
  measurementId: "G-R46NCGE0GL"
};

const app = initializeApp(firebaseConfig);
export const db = getFirestore(app); 