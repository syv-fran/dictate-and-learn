
import 'bootstrap/dist/css/bootstrap.css'
import './assets/main.css'

import { createApp } from 'vue'
import App from './App.vue'
 
import { library } from '@fortawesome/fontawesome-svg-core'; 
import { faCircleXmark ,faCircleStop, faCirclePlay, faPhone, faCircleCheck,faCirclePause,faMicrophone,faCopy} from '@fortawesome/free-solid-svg-icons';
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome';

library.add(faCircleXmark,faCircleStop,faCirclePlay, faPhone, faCircleCheck,faCirclePause,faMicrophone,faCopy);
const app = createApp(App);

app.component("font-awesome-icon", FontAwesomeIcon)
.mount("#app");