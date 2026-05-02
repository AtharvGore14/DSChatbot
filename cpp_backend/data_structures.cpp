#include <algorithm>
#include <cmath>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <queue>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using namespace std;

vector<string> split(const string &s, char sep) {
    vector<string> out;
    string item;
    stringstream ss(s);
    while (getline(ss, item, sep)) {
        if (!item.empty()) {
            out.push_back(item);
        }
    }
    return out;
}

vector<int> parse_ints(const string &csv) {
    vector<int> nums;
    vector<string> parts = split(csv, ',');
    for (const string &p : parts) {
        nums.push_back(stoi(p));
    }
    return nums;
}

string escape_json(const string &s) {
    string out;
    for (char c : s) {
        if (c == '"' || c == '\\') {
            out += '\\';
        }
        out += c;
    }
    return out;
}

string json_arr_str(const vector<string> &arr) {
    ostringstream out;
    out << "[";
    for (size_t i = 0; i < arr.size(); ++i) {
        if (i) out << ",";
        out << "\"" << escape_json(arr[i]) << "\"";
    }
    out << "]";
    return out.str();
}

string json_arr_int(const vector<int> &arr) {
    ostringstream out;
    out << "[";
    for (size_t i = 0; i < arr.size(); ++i) {
        if (i) out << ",";
        out << arr[i];
    }
    out << "]";
    return out.str();
}

class AVLTree {
public:
    struct Node {
        int key;
        int h;
        Node *left;
        Node *right;
        explicit Node(int v) : key(v), h(1), left(nullptr), right(nullptr) {}
    };

    Node *root = nullptr;

    int height(Node *n) { return n ? n->h : 0; }
    int balance(Node *n) { return n ? height(n->left) - height(n->right) : 0; }

    Node *right_rotate(Node *y) {
        Node *x = y->left;
        Node *t2 = x->right;
        x->right = y;
        y->left = t2;
        y->h = 1 + max(height(y->left), height(y->right));
        x->h = 1 + max(height(x->left), height(x->right));
        return x;
    }

    Node *left_rotate(Node *x) {
        Node *y = x->right;
        Node *t2 = y->left;
        y->left = x;
        x->right = t2;
        x->h = 1 + max(height(x->left), height(x->right));
        y->h = 1 + max(height(y->left), height(y->right));
        return y;
    }

    Node *insert(Node *node, int key) {
        if (!node) return new Node(key);
        if (key < node->key) node->left = insert(node->left, key);
        else if (key > node->key) node->right = insert(node->right, key);
        else return node;
        node->h = 1 + max(height(node->left), height(node->right));
        int b = balance(node);
        if (b > 1 && key < node->left->key) return right_rotate(node);
        if (b < -1 && key > node->right->key) return left_rotate(node);
        if (b > 1 && key > node->left->key) {
            node->left = left_rotate(node->left);
            return right_rotate(node);
        }
        if (b < -1 && key < node->right->key) {
            node->right = right_rotate(node->right);
            return left_rotate(node);
        }
        return node;
    }

    Node *min_node(Node *n) {
        Node *cur = n;
        while (cur->left) cur = cur->left;
        return cur;
    }

    Node *delete_node(Node *node, int key) {
        if (!node) return node;
        if (key < node->key) node->left = delete_node(node->left, key);
        else if (key > node->key) node->right = delete_node(node->right, key);
        else {
            if (!node->left || !node->right) {
                Node *tmp = node->left ? node->left : node->right;
                if (!tmp) {
                    tmp = node;
                    node = nullptr;
                } else {
                    *node = *tmp;
                }
                delete tmp;
            } else {
                Node *tmp = min_node(node->right);
                node->key = tmp->key;
                node->right = delete_node(node->right, tmp->key);
            }
        }
        if (!node) return node;
        node->h = 1 + max(height(node->left), height(node->right));
        int b = balance(node);
        if (b > 1 && balance(node->left) >= 0) return right_rotate(node);
        if (b > 1 && balance(node->left) < 0) {
            node->left = left_rotate(node->left);
            return right_rotate(node);
        }
        if (b < -1 && balance(node->right) <= 0) return left_rotate(node);
        if (b < -1 && balance(node->right) > 0) {
            node->right = right_rotate(node->right);
            return left_rotate(node);
        }
        return node;
    }

    void inorder(Node *n, vector<int> &out) {
        if (!n) return;
        inorder(n->left, out);
        out.push_back(n->key);
        inorder(n->right, out);
    }
};

struct TrieNode {
    bool is_end = false;
    unordered_map<char, TrieNode *> next;
};

class Trie {
    TrieNode *root;
    void collect(TrieNode *node, string cur, vector<string> &out) {
        if (node->is_end) out.push_back(cur);
        for (auto &kv : node->next) collect(kv.second, cur + kv.first, out);
    }

public:
    Trie() { root = new TrieNode(); }
    void insert(const string &word) {
        TrieNode *cur = root;
        for (char c : word) {
            if (!cur->next.count(c)) cur->next[c] = new TrieNode();
            cur = cur->next[c];
        }
        cur->is_end = true;
    }
    vector<string> suggestions(const string &prefix) {
        TrieNode *cur = root;
        for (char c : prefix) {
            if (!cur->next.count(c)) return {};
            cur = cur->next[c];
        }
        vector<string> out;
        collect(cur, prefix, out);
        sort(out.begin(), out.end());
        return out;
    }
};

class MaxHeap {
    vector<int> arr;
    void heapify_down(int i) {
        int n = static_cast<int>(arr.size());
        while (true) {
            int largest = i, l = 2 * i + 1, r = 2 * i + 2;
            if (l < n && arr[l] > arr[largest]) largest = l;
            if (r < n && arr[r] > arr[largest]) largest = r;
            if (largest == i) break;
            swap(arr[i], arr[largest]);
            i = largest;
        }
    }
    void heapify_up(int i) {
        while (i > 0) {
            int p = (i - 1) / 2;
            if (arr[p] >= arr[i]) break;
            swap(arr[p], arr[i]);
            i = p;
        }
    }

public:
    void insert(int x) {
        arr.push_back(x);
        heapify_up(static_cast<int>(arr.size()) - 1);
    }
    int extract_max() {
        if (arr.empty()) return numeric_limits<int>::min();
        int top = arr[0];
        arr[0] = arr.back();
        arr.pop_back();
        if (!arr.empty()) heapify_down(0);
        return top;
    }
    vector<int> top_k(int k) {
        vector<int> out;
        while (k-- > 0 && !arr.empty()) out.push_back(extract_max());
        return out;
    }
};

class Graph {
    unordered_map<string, vector<pair<string, int>>> adj;

public:
    void add_edge(const string &u, const string &v, int w = 1) {
        adj[u].push_back({v, w});
        adj[v].push_back({u, w});
    }

    vector<string> bfs(const string &start) {
        if (!adj.count(start)) return {};
        queue<string> q;
        unordered_map<string, bool> vis;
        vector<string> out;
        q.push(start);
        vis[start] = true;
        while (!q.empty()) {
            string u = q.front();
            q.pop();
            out.push_back(u);
            for (auto &e : adj[u]) {
                if (!vis[e.first]) {
                    vis[e.first] = true;
                    q.push(e.first);
                }
            }
        }
        return out;
    }

    vector<string> dfs(const string &start) {
        vector<string> out;
        unordered_map<string, bool> vis;
        function<void(const string &)> go = [&](const string &u) {
            vis[u] = true;
            out.push_back(u);
            for (auto &e : adj[u]) if (!vis[e.first]) go(e.first);
        };
        if (adj.count(start)) go(start);
        return out;
    }

    map<string, int> dijkstra(const string &start) {
        map<string, int> dist;
        for (const auto &kv : adj) dist[kv.first] = numeric_limits<int>::max() / 2;
        if (!adj.count(start)) return dist;
        dist[start] = 0;
        using P = pair<int, string>;
        priority_queue<P, vector<P>, greater<P>> pq;
        pq.push(make_pair(0, start));
        while (!pq.empty()) {
            P top = pq.top();
            int d = top.first;
            string u = top.second;
            pq.pop();
            if (d != dist[u]) continue;
            for (auto &e : adj[u]) {
                int nd = d + e.second;
                if (nd < dist[e.first]) {
                    dist[e.first] = nd;
                    pq.push(make_pair(nd, e.first));
                }
            }
        }
        return dist;
    }
};

class HashTable {
    static const int BUCKETS = 101;
    vector<vector<pair<string, string>>> table;
    int hash_fn(const string &key) {
        long long h = 0;
        for (char c : key) h = (h * 131 + c) % BUCKETS;
        return static_cast<int>(h);
    }

public:
    HashTable() : table(BUCKETS) {}
    void put(const string &k, const string &v) {
        int i = hash_fn(k);
        for (auto &kv : table[i]) {
            if (kv.first == k) {
                kv.second = v;
                return;
            }
        }
        table[i].push_back({k, v});
    }
    string get(const string &k) {
        int i = hash_fn(k);
        for (auto &kv : table[i]) if (kv.first == k) return kv.second;
        return "";
    }
};

struct BSTNode {
    int key;
    BSTNode *left;
    BSTNode *right;
    explicit BSTNode(int v) : key(v), left(nullptr), right(nullptr) {}
};

BSTNode *bst_insert(BSTNode *n, int x) {
    if (!n) return new BSTNode(x);
    if (x < n->key) n->left = bst_insert(n->left, x);
    else if (x > n->key) n->right = bst_insert(n->right, x);
    return n;
}

void bst_inorder(BSTNode *n, vector<int> &out) {
    if (!n) return;
    bst_inorder(n->left, out);
    out.push_back(n->key);
    bst_inorder(n->right, out);
}

class SimpleStack {
    vector<string> st;

public:
    void push(const string &x) { st.push_back(x); }
    string pop() {
        if (st.empty()) return "";
        string v = st.back();
        st.pop_back();
        return v;
    }
};

class SimpleQueue {
    queue<string> q;

public:
    void push(const string &x) { q.push(x); }
    string pop() {
        if (q.empty()) return "";
        string v = q.front();
        q.pop();
        return v;
    }
};

void merge_sort(vector<int> &a, int l, int r) {
    if (l >= r) return;
    int m = (l + r) / 2;
    merge_sort(a, l, m);
    merge_sort(a, m + 1, r);
    vector<int> tmp;
    int i = l, j = m + 1;
    while (i <= m && j <= r) tmp.push_back(a[i] <= a[j] ? a[i++] : a[j++]);
    while (i <= m) tmp.push_back(a[i++]);
    while (j <= r) tmp.push_back(a[j++]);
    for (int k = l; k <= r; ++k) a[k] = tmp[k - l];
}

int partition_q(vector<int> &a, int l, int r) {
    int p = a[r], i = l - 1;
    for (int j = l; j < r; ++j) {
        if (a[j] <= p) {
            ++i;
            swap(a[i], a[j]);
        }
    }
    swap(a[i + 1], a[r]);
    return i + 1;
}

void quick_sort(vector<int> &a, int l, int r) {
    if (l >= r) return;
    int pi = partition_q(a, l, r);
    quick_sort(a, l, pi - 1);
    quick_sort(a, pi + 1, r);
}

void heap_sort(vector<int> &a) {
    priority_queue<int, vector<int>, greater<int>> pq(a.begin(), a.end());
    for (int &x : a) {
        x = pq.top();
        pq.pop();
    }
}

int linear_search(const vector<int> &a, int target) {
    for (size_t i = 0; i < a.size(); ++i) if (a[i] == target) return static_cast<int>(i);
    return -1;
}

int binary_search_idx(const vector<int> &a, int target) {
    int l = 0, r = static_cast<int>(a.size()) - 1;
    while (l <= r) {
        int m = l + (r - l) / 2;
        if (a[m] == target) return m;
        if (a[m] < target) l = m + 1;
        else r = m - 1;
    }
    return -1;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        cout << "{\"status\":\"ok\",\"message\":\"cpp ds engine ready\"}";
        return 0;
    }

    string cmd = argv[1];
    try {
        if (cmd == "health") {
            cout << "{\"status\":\"ok\",\"engine\":\"cpp_ds\",\"file\":\"data_structures.cpp\"}";
            return 0;
        }

        if (cmd == "sort" && argc >= 4) {
            string algo = argv[2];
            vector<int> nums = parse_ints(argv[3]);
            if (nums.empty()) {
                cout << "{\"status\":\"error\",\"message\":\"empty input\"}";
                return 1;
            }
            if (algo == "merge") merge_sort(nums, 0, static_cast<int>(nums.size()) - 1);
            else if (algo == "quick") quick_sort(nums, 0, static_cast<int>(nums.size()) - 1);
            else if (algo == "heap") heap_sort(nums);
            else {
                cout << "{\"status\":\"error\",\"message\":\"unknown sort algo\"}";
                return 1;
            }
            cout << "{\"status\":\"ok\",\"sorted\":" << json_arr_int(nums) << "}";
            return 0;
        }

        if (cmd == "search" && argc >= 5) {
            string algo = argv[2];
            vector<int> nums = parse_ints(argv[3]);
            int target = stoi(argv[4]);
            int idx = -1;
            if (algo == "linear") idx = linear_search(nums, target);
            else if (algo == "binary") idx = binary_search_idx(nums, target);
            else {
                cout << "{\"status\":\"error\",\"message\":\"unknown search algo\"}";
                return 1;
            }
            cout << "{\"status\":\"ok\",\"index\":" << idx << "}";
            return 0;
        }

        if (cmd == "trie" && argc >= 3) {
            Trie trie;
            vector<string> symbols = {
                "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ITC.NS",
                "WIPRO.NS", "SBIN.NS", "HCLTECH.NS", "ICICIBANK.NS", "LT.NS",
                "AXISBANK.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "BHARTIARTL.NS",
                "ASIANPAINT.NS", "MARUTI.NS", "TITAN.NS", "SUNPHARMA.NS",
                "ULTRACEMCO.NS", "NESTLEIND.NS", "POWERGRID.NS", "NTPC.NS"
            };
            for (const string &s : symbols) trie.insert(s);
            string prefix = argv[2];
            vector<string> sug = trie.suggestions(prefix);
            cout << "{\"status\":\"ok\",\"suggestions\":" << json_arr_str(sug) << "}";
            return 0;
        }

        if (cmd == "avl" && argc >= 3) {
            vector<int> nums = parse_ints(argv[2]);
            AVLTree avl;
            for (int x : nums) avl.root = avl.insert(avl.root, x);
            vector<int> inorder_vals;
            avl.inorder(avl.root, inorder_vals);
            cout << "{\"status\":\"ok\",\"inorder\":" << json_arr_int(inorder_vals) << "}";
            return 0;
        }

        if (cmd == "heap" && argc >= 4) {
            vector<int> nums = parse_ints(argv[2]);
            int k = stoi(argv[3]);
            MaxHeap h;
            for (int x : nums) h.insert(x);
            vector<int> top = h.top_k(k);
            cout << "{\"status\":\"ok\",\"top\":" << json_arr_int(top) << "}";
            return 0;
        }

        if (cmd == "graph" && argc >= 4) {
            string type = argv[2];
            string start = argv[3];
            Graph g;
            g.add_edge("IT", "BANKING", 2);
            g.add_edge("IT", "PHARMA", 4);
            g.add_edge("BANKING", "AUTO", 3);
            g.add_edge("PHARMA", "FMCG", 5);
            g.add_edge("AUTO", "FMCG", 1);
            if (type == "bfs") {
                vector<string> out = g.bfs(start);
                cout << "{\"status\":\"ok\",\"traversal\":" << json_arr_str(out) << "}";
            } else if (type == "dfs") {
                vector<string> out = g.dfs(start);
                cout << "{\"status\":\"ok\",\"traversal\":" << json_arr_str(out) << "}";
            } else if (type == "dijkstra") {
                map<string, int> dist = g.dijkstra(start);
                cout << "{\"status\":\"ok\",\"distance\":{";
                bool first = true;
                for (const auto &kv : dist) {
                    if (!first) cout << ",";
                    first = false;
                    cout << "\"" << kv.first << "\":" << kv.second;
                }
                cout << "}}";
            } else {
                cout << "{\"status\":\"error\",\"message\":\"unknown graph algo\"}";
                return 1;
            }
            return 0;
        }

        if (cmd == "hash" && argc >= 4) {
            HashTable table;
            table.put("RELIANCE.NS", "Energy");
            table.put("TCS.NS", "IT");
            table.put("INFY.NS", "IT");
            string key = argv[2];
            string fallback = argv[3];
            string found = table.get(key);
            if (found.empty()) found = fallback;
            cout << "{\"status\":\"ok\",\"value\":\"" << escape_json(found) << "\"}";
            return 0;
        }

        if (cmd == "bst" && argc >= 3) {
            vector<int> nums = parse_ints(argv[2]);
            BSTNode *root = nullptr;
            for (int x : nums) root = bst_insert(root, x);
            vector<int> out;
            bst_inorder(root, out);
            cout << "{\"status\":\"ok\",\"inorder\":" << json_arr_int(out) << "}";
            return 0;
        }

        if (cmd == "stack" && argc >= 3) {
            vector<string> items = split(argv[2], ',');
            SimpleStack st;
            for (const string &x : items) st.push(x);
            cout << "{\"status\":\"ok\",\"popped\":\"" << escape_json(st.pop()) << "\"}";
            return 0;
        }

        if (cmd == "queue" && argc >= 3) {
            vector<string> items = split(argv[2], ',');
            SimpleQueue qu;
            for (const string &x : items) qu.push(x);
            cout << "{\"status\":\"ok\",\"dequeued\":\"" << escape_json(qu.pop()) << "\"}";
            return 0;
        }

        cout << "{\"status\":\"error\",\"message\":\"unknown command\"}";
        return 1;
    } catch (const exception &e) {
        cout << "{\"status\":\"error\",\"message\":\"" << escape_json(e.what()) << "\"}";
        return 1;
    }
}
